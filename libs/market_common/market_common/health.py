"""Routes de santé réutilisables par tous les services.

- `GET /healthz` (vivacité) : le processus répond ; aucune dépendance n'est interrogée.
- `GET /readyz` (préparation) : exécute en parallèle les sondes injectées par le service (base, Kafka...),
  chacune bornée par un délai ; 503 si une sonde rend faux, lève une exception ou expire.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter
from fastapi.responses import JSONResponse

HealthCheck = Callable[[], Awaitable[bool]]

logger = logging.getLogger(__name__)


async def _run_check(name: str, check: HealthCheck, timeout_seconds: float) -> bool:
    """Exécute une sonde ; un échec est journalisé et compté comme indisponible, jamais avalé en silence."""
    deadline = asyncio.timeout(timeout_seconds)
    try:
        async with deadline:
            result = await check()
    except TimeoutError:
        if not deadline.expired():  # TimeoutError levé par la sonde elle-même (connexion, socket) : c'est une erreur
            logger.exception("sonde de préparation %s en erreur", name)
            return False
        logger.warning("sonde de préparation %s expirée après %.3f s", name, timeout_seconds)
        return False
    except Exception:
        logger.exception("sonde de préparation %s en erreur", name)
        return False
    if result is not True:
        logger.warning("sonde de préparation %s en échec", name)
        return False
    return True


def health_router(checks: Mapping[str, HealthCheck] | None = None, *, timeout_seconds: float = 2.0) -> APIRouter:
    """Fabrique le routeur `/healthz` et `/readyz` ; `checks` associe un nom à une sonde asynchrone."""
    probes = dict(checks or {})
    router = APIRouter(tags=["santé"])

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    async def readyz() -> JSONResponse:
        names = list(probes)
        results = await asyncio.gather(*(_run_check(n, probes[n], timeout_seconds) for n in names))
        outcome = dict(zip(names, results, strict=True))
        ready = all(results)
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "unavailable", "checks": outcome},
        )

    return router
