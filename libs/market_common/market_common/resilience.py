"""Résilience des appels sortants : délai par appel, retry idempotent, circuit breaker, bulkhead.

Bibliothèque standard seule. Chaque mécanisme reçoit une *fabrique* d'appel (`Callable[[], Awaitable[T]]`) et non
une coroutine déjà créée, pour pouvoir la relancer à chaque tentative. Composition recommandée : voir
`call_resilient` et le README de `market_common`.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

type Operation[T] = Callable[[], Awaitable[T]]
type Sleep = Callable[[float], Awaitable[None]]
type Clock = Callable[[], float]

MAX_BACKOFF_SECONDS = 0.2


class CallTimeoutError(TimeoutError):
    """L'appel a dépassé son délai et a été annulé."""


class CircuitOpenError(Exception):
    """Refus immédiat : le circuit de la dépendance est ouvert. Jamais rejouée par `RetryPolicy`."""

    def __init__(self, name: str) -> None:
        super().__init__(f"circuit ouvert : {name}")
        self.name = name


async def with_timeout[T](operation: Operation[T], seconds: float) -> T:
    """Exécute l'appel ; au-delà de `seconds`, l'annule et lève `CallTimeoutError`."""
    if seconds <= 0:
        raise ValueError("le délai doit être strictement positif")
    scope = asyncio.timeout(seconds)
    try:
        async with scope:
            return await operation()
    except TimeoutError as exc:
        if not scope.expired():
            raise  # délai propre à l'appel lui-même : il n'est pas le nôtre
        raise CallTimeoutError(f"appel interrompu après {seconds} s") from exc


class BulkheadFullError(Exception):
    """Refus immédiat : toutes les places du bulkhead et de sa file sont prises. Jamais rejouée par `RetryPolicy`."""

    def __init__(self, name: str) -> None:
        super().__init__(f"bulkhead plein : {name}")
        self.name = name


NEVER_RETRIED: tuple[type[Exception], ...] = (CircuitOpenError, BulkheadFullError)


@dataclass(frozen=True)
class RetryPolicy:
    """Rejoue un appel **idempotent** sur les seules exceptions désignées par `retry_on`.

    `NEVER_RETRIED` (circuit ouvert, bulkhead plein) n'est jamais rejoué, même désigné.

    Un appel déclaré non idempotent n'est tenté qu'une fois. Après `attempts` tentatives, l'exception d'origine
    de la dernière tentative est relevée telle quelle. L'attente entre deux tentatives est fixe et bornée.
    """

    retry_on: tuple[type[Exception], ...]
    attempts: int = 3
    backoff_seconds: float = 0.1
    sleep: Sleep = field(default=asyncio.sleep, repr=False)

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("au moins une tentative")
        if not 0 <= self.backoff_seconds <= MAX_BACKOFF_SECONDS:
            raise ValueError(f"attente entre tentatives comprise entre 0 et {MAX_BACKOFF_SECONDS} s")

    async def call[T](self, operation: Operation[T], *, idempotent: bool) -> T:
        attempts = self.attempts if idempotent else 1
        for attempt in range(1, attempts + 1):
            try:
                return await operation()
            except NEVER_RETRIED:
                raise
            except self.retry_on:
                if attempt == attempts:
                    raise
            await self.sleep(self.backoff_seconds)
        raise AssertionError("inaccessible : la dernière tentative rend ou lève")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Coupe les appels vers une dépendance après `failure_threshold` échecs consécutifs.

    - Seules les exceptions de `failure_types` comptent comme échec (délai, connexion, 5xx) ; toute autre exception
      (résultat métier : 402, 409) prouve que la dépendance répond et vaut un succès.
    - Chaque appel échoué compte ; un succès remet le compteur à zéro.
    - Ouvert : refus immédiat par `CircuitOpenError`, sans appeler la dépendance.
    - Après `reset_timeout_seconds`, demi-ouvert : un seul appel d'essai passe ; réussi, il referme le circuit,
      échoué, il le rouvre pour un nouveau délai.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int,
        reset_timeout_seconds: float,
        failure_types: tuple[type[Exception], ...],
        clock: Clock = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("seuil d'ouverture d'au moins un échec")
        if reset_timeout_seconds <= 0:
            raise ValueError("délai de réarmement strictement positif")
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.failure_types = failure_types
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if self._trial_in_flight or self._clock() - self._opened_at >= self.reset_timeout_seconds:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    async def call[T](self, operation: Operation[T]) -> T:
        state = self.state
        if state is CircuitState.OPEN or (state is CircuitState.HALF_OPEN and self._trial_in_flight):
            raise CircuitOpenError(self.name)
        trial = state is CircuitState.HALF_OPEN
        if trial:
            self._trial_in_flight = True
        try:
            result = await operation()
        except Exception as exc:
            self._record(trial=trial, failed=isinstance(exc, self.failure_types))
            raise
        finally:
            if trial:
                self._trial_in_flight = False
        self._record(trial=trial, failed=False)
        return result

    def _record(self, *, trial: bool, failed: bool) -> None:
        if not trial and self._opened_at is not None:
            return  # appel admis avant l'ouverture : son issue ne change plus l'état
        if not failed:
            self._failures = 0
            self._opened_at = None
            return
        self._failures += 1
        if trial or self._failures >= self.failure_threshold:
            self._opened_at = self._clock()


class Bulkhead:
    """Cloisonne une dépendance : au plus `max_concurrent` appels simultanés et `max_queue` en attente.

    Au-delà, l'appel est refusé tout de suite par `BulkheadFullError`, sans appeler la dépendance.
    """

    def __init__(self, name: str, *, max_concurrent: int, max_queue: int = 0) -> None:
        if max_concurrent < 1:
            raise ValueError("au moins un appel simultané")
        if max_queue < 0:
            raise ValueError("file d'attente de taille positive ou nulle")
        self.name = name
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self._slots = asyncio.Semaphore(max_concurrent)
        self._admitted = 0

    async def call[T](self, operation: Operation[T]) -> T:
        if self._admitted >= self.max_concurrent + self.max_queue:
            raise BulkheadFullError(self.name)
        self._admitted += 1
        try:
            async with self._slots:
                return await operation()
        finally:
            self._admitted -= 1


async def call_resilient[T](
    operation: Operation[T],
    *,
    idempotent: bool,
    timeout_seconds: float,
    retry: RetryPolicy,
    breaker: CircuitBreaker,
    bulkhead: Bulkhead,
) -> T:
    """Composition de référence : retry autour du circuit autour du délai par tentative, le tout dans le bulkhead.

    Le bulkhead n'est pris qu'une fois pour toutes les tentatives ; chaque tentative passe par le circuit (qui la
    compte si elle échoue) et a son propre délai. Pour qu'un délai dépassé compte et soit rejoué, `CallTimeoutError`
    doit figurer dans `breaker.failure_types` et `retry.retry_on`.
    """

    async def attempt() -> T:
        return await breaker.call(lambda: with_timeout(operation, timeout_seconds))

    return await bulkhead.call(lambda: retry.call(attempt, idempotent=idempotent))
