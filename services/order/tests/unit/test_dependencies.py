import httpx
import pytest
from market_common.resilience import CircuitState
from market_order.adapters.dependencies import Dependency
from market_order.config import Settings
from pydantic import ValidationError


def settings(**values):
    return Settings.model_validate({"ORDERS_DB_PASSWORD": "unit-only", **values})


@pytest.mark.parametrize(
    "values",
    [
        {"retry_attempts": 2, "breaker_failure_threshold": 3},
        {"retry_backoff_seconds": 0.21},
    ],
)
def test_settings_reject_incoherent_resilience(values):
    with pytest.raises(ValidationError):
        settings(**values)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [402, 409, 422])
async def test_business_4xx_is_neither_retried_nor_counted_by_breaker(status):
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        config = settings()
        dependency = Dependency("payment", "http://payment", 1, http, config)
        for attempt in range(config.breaker_failure_threshold):
            result = await dependency.post("/v1/payments", {}, {})
            assert result.status_code == status
            assert len(calls) == attempt + 1
        assert dependency.breaker.state == CircuitState.CLOSED
        following = await dependency.post("/v1/payments", {}, {})
        assert following.status_code == status
        assert len(calls) == config.breaker_failure_threshold + 1
        assert dependency.breaker.state == CircuitState.CLOSED


@pytest.mark.anyio
@pytest.mark.parametrize(
    "errors, expected",
    [
        ([httpx.ConnectError("refus")] * 3, "NOT_SENT"),
        ([httpx.ReadError("après envoi"), httpx.ConnectError("refus"), httpx.ConnectError("refus")], "UNKNOWN"),
        ([503, httpx.ConnectError("refus"), httpx.ConnectError("refus")], "UNKNOWN"),
    ],
)
async def test_payment_classification_retains_evidence_from_all_attempts(errors, expected):
    from datetime import UTC, datetime
    from decimal import Decimal

    from market_order.adapters.gateways import HttpPayment
    from market_order.domain.models import Line, Saga

    attempts = []

    async def respond(request):
        error = errors[len(attempts)]
        attempts.append(request)
        if isinstance(error, Exception):
            raise error
        return httpx.Response(error)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        config = settings(retry_backoff_seconds=0)
        dependency = Dependency("payment", "http://payment", 0.1, http, config)
        gateway = HttpPayment(dependency, "local")
        saga = Saga("order", datetime.now(UTC), "client", (Line("sku", 1),), Decimal("10"), "owner")
        assert await gateway.pay(saga) == expected
    assert len(attempts) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("environment, forwarded", [("local", True), ("production", False)])
async def test_failure_simulation_is_forwarded_only_locally(environment, forwarded):
    from datetime import UTC, datetime
    from decimal import Decimal

    from market_order.adapters.gateways import HttpPayment
    from market_order.domain.models import Saga

    seen = []

    async def respond(request):
        seen.append(request)
        return httpx.Response(201, json={"status": "CAPTURED", "payment_id": "payment"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        dependency = Dependency("payment", "http://payment", 1, http, settings())
        saga = Saga("order", datetime.now(UTC), "client", (), Decimal("10"), "owner", simulate_failure=True)
        await HttpPayment(dependency, environment).pay(saga)
    assert ("X-Simulate-Failure" in seen[0].headers) == forwarded
    assert seen[0].headers["Idempotency-Key"] == "order"
