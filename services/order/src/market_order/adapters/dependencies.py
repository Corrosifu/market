import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from market_common.resilience import (
    Bulkhead,
    BulkheadFullError,
    CallTimeoutError,
    CircuitBreaker,
    CircuitOpenError,
    RetryPolicy,
    call_resilient,
)
from market_order.config import Settings


class UpstreamServerError(Exception):
    """Une réponse 5xx de la dépendance."""


FAILURES = (CallTimeoutError, httpx.TransportError, UpstreamServerError)
UNAVAILABLE = (*FAILURES, CircuitOpenError, BulkheadFullError)


@dataclass
class AttemptEvidence:
    uncertain: bool = False


class Dependency:
    def __init__(
        self,
        name: str,
        url: str,
        timeout: float,
        client: httpx.AsyncClient,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url.rstrip("/")
        self.client = client
        self.timeout = timeout
        self.breaker = CircuitBreaker(
            name,
            failure_threshold=settings.breaker_failure_threshold,
            reset_timeout_seconds=settings.breaker_reset_seconds,
            failure_types=FAILURES,
            clock=clock,
        )
        self.bulkhead = Bulkhead(name, max_concurrent=settings.bulkhead_max_concurrent, max_queue=0)
        self.retry = RetryPolicy(
            retry_on=FAILURES, attempts=settings.retry_attempts, backoff_seconds=settings.retry_backoff_seconds
        )

    async def post(
        self,
        path: str,
        body: Mapping[str, object] | None,
        headers: Mapping[str, str],
        evidence: AttemptEvidence | None = None,
    ) -> httpx.Response:
        async def operation() -> httpx.Response:
            try:
                response = await self.client.post(self.url + path, json=body, headers=headers, timeout=None)
            except httpx.ConnectError:
                raise
            except BaseException:
                if evidence is not None:
                    evidence.uncertain = True
                raise
            if response.status_code >= 500:
                if evidence is not None:
                    evidence.uncertain = True
                raise UpstreamServerError(f"Dépendance en erreur ({response.status_code})")
            return response

        return await call_resilient(
            operation,
            idempotent=True,
            timeout_seconds=self.timeout,
            retry=self.retry,
            breaker=self.breaker,
            bulkhead=self.bulkhead,
        )
