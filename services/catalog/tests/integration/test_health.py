"""Santé du catalogue : vivacité sans dépendance, préparation conditionnée à une réponse de MongoDB."""
from __future__ import annotations

from fastapi.testclient import TestClient


class UnreachableCatalog:
    async def ping(self) -> bool:
        raise ConnectionError("MongoDB injoignable")


def test_liveness_and_readiness_with_mongodb(api: TestClient) -> None:
    assert api.get("/healthz").json() == {"status": "ok"}

    ready = api.get("/readyz")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "checks": {"mongo": True}}


def test_not_ready_when_mongodb_does_not_answer(api: TestClient) -> None:
    api.app.state.catalog = UnreachableCatalog()  # type: ignore[attr-defined]

    ready = api.get("/readyz")

    assert ready.status_code == 503
    assert ready.json()["checks"] == {"mongo": False}
    assert api.get("/healthz").status_code == 200
