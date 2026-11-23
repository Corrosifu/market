"""Comportement des mécanismes de résilience : délai, retry idempotent, circuit breaker, bulkhead.

Horloge, attentes et appels sont contrôlés par le test : aucune attente réelle de plus d'une fraction de seconde.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from market_common.resilience import (
    Bulkhead,
    BulkheadFullError,
    CallTimeoutError,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    RetryPolicy,
    call_resilient,
    with_timeout,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RecordedSleeps:
    """Remplace `asyncio.sleep` : note les attentes demandées sans attendre."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class FakeClock:
    """Horloge monotone avancée à la main par le test."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FailingCall:
    """Appel compté qui lève toujours la même exception."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        raise self.error


@pytest.mark.anyio
async def test_timeout_cancels_call_after_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'horloge de la boucle est avancée à la main : un délai de 10 s expire sans attente réelle."""
    loop = asyncio.get_running_loop()
    real_time = loop.time
    skipped = 0.0
    monkeypatch.setattr(loop, "time", lambda: real_time() + skipped)
    cancelled = asyncio.Event()

    async def hangs_forever() -> str:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "jamais"

    started = time.perf_counter()
    call = asyncio.create_task(with_timeout(hangs_forever, seconds=10.0))
    await asyncio.sleep(0)
    skipped = 9.9
    await asyncio.sleep(0)
    assert not call.done()

    skipped = 10.0
    for _ in range(10):  # quelques tours de boucle, jamais d'attente : un délai ignoré échoue au lieu de bloquer
        await asyncio.sleep(0)
    if not call.done():
        call.cancel()
        pytest.fail("l'appel n'a pas été interrompu au délai")
    with pytest.raises(CallTimeoutError):
        call.result()

    assert cancelled.is_set()
    assert time.perf_counter() - started < 0.5


@pytest.mark.anyio
async def test_retry_makes_exact_number_of_attempts_on_idempotent_call() -> None:
    sleeps = RecordedSleeps()
    error = ConnectionError("payment injoignable")
    call = FailingCall(error)
    retry = RetryPolicy(retry_on=(ConnectionError,), attempts=3, backoff_seconds=0.1, sleep=sleeps)

    with pytest.raises(ConnectionError) as raised:
        await retry.call(call, idempotent=True)

    assert call.calls == 3
    assert raised.value is error
    assert sleeps.delays == [0.1, 0.1]


@pytest.mark.anyio
async def test_retry_never_repeats_non_idempotent_call() -> None:
    sleeps = RecordedSleeps()
    call = FailingCall(ConnectionError("payment injoignable"))
    retry = RetryPolicy(retry_on=(ConnectionError,), attempts=3, sleep=sleeps)

    with pytest.raises(ConnectionError):
        await retry.call(call, idempotent=False)

    assert call.calls == 1
    assert sleeps.delays == []


@pytest.mark.anyio
async def test_retry_replays_only_designated_exceptions_and_stops_on_success() -> None:
    sleeps = RecordedSleeps()
    not_designated = FailingCall(ValueError("402 paiement refusé"))
    retry = RetryPolicy(retry_on=(ConnectionError,), attempts=3, sleep=sleeps)

    with pytest.raises(ValueError):
        await retry.call(not_designated, idempotent=True)
    assert not_designated.calls == 1

    outcomes: list[Exception | str] = [ConnectionError("coupure"), "ok", "jamais"]

    async def flaky() -> str:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert await retry.call(flaky, idempotent=True) == "ok"
    assert outcomes == ["jamais"]


def test_retry_backoff_is_bounded_by_default() -> None:
    assert RetryPolicy(retry_on=(ConnectionError,)).backoff_seconds <= 0.2
    with pytest.raises(ValueError):
        RetryPolicy(retry_on=(ConnectionError,), backoff_seconds=0.5)
    with pytest.raises(ValueError):
        RetryPolicy(retry_on=(ConnectionError,), attempts=0)


class BusinessError(Exception):
    """Résultat métier (402, 409) : ne doit pas compter comme panne."""


async def succeeds() -> str:
    return "ok"


def breaker_for(clock: FakeClock, threshold: int = 3) -> CircuitBreaker:
    return CircuitBreaker(
        "payment", failure_threshold=threshold, reset_timeout_seconds=5.0, failure_types=(ConnectionError,), clock=clock
    )


@pytest.mark.anyio
async def test_breaker_opens_at_threshold_then_fails_fast() -> None:
    breaker = breaker_for(FakeClock(), threshold=3)
    down = FailingCall(ConnectionError("payment arrêté"))

    for _ in range(2):
        with pytest.raises(ConnectionError):
            await breaker.call(down)
    assert breaker.state is CircuitState.CLOSED
    with pytest.raises(ConnectionError):
        await breaker.call(down)
    assert breaker.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        await breaker.call(down)
    assert down.calls == 3
    assert breaker.state == "open"


@pytest.mark.anyio
async def test_breaker_half_open_closes_after_success() -> None:
    clock = FakeClock()
    breaker = breaker_for(clock, threshold=1)
    with pytest.raises(ConnectionError):
        await breaker.call(FailingCall(ConnectionError("payment arrêté")))

    clock.now += 4.9
    assert breaker.state is CircuitState.OPEN
    clock.now += 0.1
    assert breaker.state is CircuitState.HALF_OPEN

    assert await breaker.call(succeeds) == "ok"
    assert breaker.state is CircuitState.CLOSED


@pytest.mark.anyio
async def test_breaker_half_open_reopens_after_failed_trial() -> None:
    clock = FakeClock()
    breaker = breaker_for(clock, threshold=1)
    down = FailingCall(ConnectionError("payment arrêté"))
    with pytest.raises(ConnectionError):
        await breaker.call(down)

    clock.now += 5.0
    with pytest.raises(ConnectionError):
        await breaker.call(down)
    assert breaker.state is CircuitState.OPEN
    clock.now += 4.9
    with pytest.raises(CircuitOpenError):
        await breaker.call(down)
    assert down.calls == 2


@pytest.mark.anyio
async def test_breaker_lets_a_single_trial_through_while_half_open() -> None:
    clock = FakeClock()
    breaker = breaker_for(clock, threshold=1)
    with pytest.raises(ConnectionError):
        await breaker.call(FailingCall(ConnectionError("payment arrêté")))
    clock.now += 5.0
    release = asyncio.Event()

    async def slow_trial() -> str:
        await release.wait()
        return "ok"

    trial = asyncio.create_task(breaker.call(slow_trial))
    await asyncio.sleep(0)
    with pytest.raises(CircuitOpenError):
        await breaker.call(succeeds)
    release.set()
    assert await trial == "ok"
    assert breaker.state is CircuitState.CLOSED


@pytest.mark.anyio
async def test_breaker_cancelled_trial_frees_the_slot_without_counting() -> None:
    clock = FakeClock()
    breaker = breaker_for(clock, threshold=1)
    with pytest.raises(ConnectionError):
        await breaker.call(FailingCall(ConnectionError("payment arrêté")))
    clock.now += 5.0

    trial = asyncio.create_task(breaker.call(asyncio.Event().wait))
    await asyncio.sleep(0)
    with pytest.raises(CircuitOpenError):
        await breaker.call(succeeds)
    trial.cancel()
    with pytest.raises(asyncio.CancelledError):
        await trial

    assert breaker.state is CircuitState.HALF_OPEN
    assert await breaker.call(succeeds) == "ok"
    assert breaker.state is CircuitState.CLOSED


@pytest.mark.anyio
async def test_breaker_ignores_outcome_of_calls_admitted_before_opening() -> None:
    clock = FakeClock()
    breaker = breaker_for(clock, threshold=1)
    release = asyncio.Event()

    async def late_success() -> str:
        await release.wait()
        return "ok"

    async def late_failure() -> str:
        await release.wait()
        raise ConnectionError("réponse tardive")

    late = [asyncio.create_task(breaker.call(late_success)), asyncio.create_task(breaker.call(late_failure))]
    await asyncio.sleep(0)
    with pytest.raises(ConnectionError):
        await breaker.call(FailingCall(ConnectionError("payment arrêté")))
    assert breaker.state is CircuitState.OPEN

    clock.now += 3.0
    release.set()
    outcomes = await asyncio.gather(*late, return_exceptions=True)
    assert outcomes[0] == "ok"
    assert isinstance(outcomes[1], ConnectionError)

    assert breaker.state is CircuitState.OPEN
    clock.now += 2.0
    assert breaker.state is CircuitState.HALF_OPEN

@pytest.mark.anyio
async def test_breaker_ignores_business_errors_and_success_resets_count() -> None:
    breaker = breaker_for(FakeClock(), threshold=2)
    down = FailingCall(ConnectionError("payment arrêté"))

    for _ in range(5):
        with pytest.raises(BusinessError):
            await breaker.call(FailingCall(BusinessError("402")))
    with pytest.raises(ConnectionError):
        await breaker.call(down)
    assert await breaker.call(succeeds) == "ok"
    with pytest.raises(ConnectionError):
        await breaker.call(down)

    assert breaker.state is CircuitState.CLOSED


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("business_error", "expected"), [(True, CircuitState.CLOSED), (False, CircuitState.OPEN)]
)
async def test_breaker_business_error_resets_failure_count(business_error: bool, expected: CircuitState) -> None:
    """Une erreur métier prouve que la dépendance répond : elle vaut un succès, pas un appel neutre."""
    breaker = breaker_for(FakeClock(), threshold=2)
    server_error = FailingCall(ConnectionError("503"))

    with pytest.raises(ConnectionError):
        await breaker.call(server_error)
    if business_error:
        with pytest.raises(BusinessError):
            await breaker.call(FailingCall(BusinessError("409")))
    with pytest.raises(ConnectionError):
        await breaker.call(server_error)

    assert breaker.state is expected

@pytest.mark.anyio
async def test_retry_counts_each_attempt_in_breaker_and_never_replays_open_circuit() -> None:
    sleeps = RecordedSleeps()
    breaker = breaker_for(FakeClock(), threshold=2)
    down = FailingCall(ConnectionError("payment arrêté"))
    retry = RetryPolicy(retry_on=(ConnectionError, CircuitOpenError), attempts=5, sleep=sleeps)

    with pytest.raises(CircuitOpenError):
        await retry.call(lambda: breaker.call(down), idempotent=True)

    assert down.calls == 2
    assert len(sleeps.delays) == 2


@pytest.mark.anyio
async def test_bulkhead_limits_concurrency() -> None:
    bulkhead = Bulkhead("payment", max_concurrent=2, max_queue=1)
    release = asyncio.Event()
    running = 0
    peak = 0

    async def held_call() -> str:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            await release.wait()
        finally:
            running -= 1
        return "ok"

    admitted = [asyncio.create_task(bulkhead.call(held_call)) for _ in range(3)]
    await asyncio.sleep(0)
    assert running == 2

    refused = FailingCall(ConnectionError("jamais appelé"))
    with pytest.raises(BulkheadFullError):
        await bulkhead.call(refused)
    assert refused.calls == 0

    release.set()
    assert await asyncio.gather(*admitted) == ["ok", "ok", "ok"]
    assert peak == 2
    assert await bulkhead.call(succeeds) == "ok"


@pytest.mark.anyio
async def test_retry_never_replays_full_bulkhead() -> None:
    sleeps = RecordedSleeps()
    bulkhead = Bulkhead("payment", max_concurrent=1)
    release = asyncio.Event()

    async def held_call() -> None:
        await release.wait()

    holder = asyncio.create_task(bulkhead.call(held_call))
    await asyncio.sleep(0)
    retry = RetryPolicy(retry_on=(Exception,), attempts=3, sleep=sleeps)

    with pytest.raises(BulkheadFullError):
        await retry.call(lambda: bulkhead.call(succeeds), idempotent=True)
    assert sleeps.delays == []

    release.set()
    await holder


@pytest.mark.anyio
async def test_composition_times_out_each_attempt_counts_it_then_fails_fast() -> None:
    sleeps = RecordedSleeps()
    breaker = CircuitBreaker(
        "payment", failure_threshold=3, reset_timeout_seconds=5.0, failure_types=(CallTimeoutError,), clock=FakeClock()
    )
    bulkhead = Bulkhead("payment", max_concurrent=1)
    retry = RetryPolicy(retry_on=(CallTimeoutError,), attempts=3, sleep=sleeps)
    calls = 0

    async def hangs_forever() -> str:
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()
        return "jamais"

    async def run(idempotent: bool) -> str:
        return await call_resilient(
            hangs_forever, idempotent=idempotent, timeout_seconds=0.02, retry=retry, breaker=breaker, bulkhead=bulkhead
        )

    with pytest.raises(CallTimeoutError):
        await run(idempotent=True)
    assert (calls, len(sleeps.delays), breaker.state) == (3, 2, CircuitState.OPEN)

    with pytest.raises(CircuitOpenError):
        await run(idempotent=True)
    assert calls == 3
    assert await bulkhead.call(succeeds) == "ok"
