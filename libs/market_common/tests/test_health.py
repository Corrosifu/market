"""Comportement des routes de santé : vivacité indépendante, préparation agrégeant des sondes asynchrones."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_common.health import health_router

Check = Callable[[], Awaitable[bool]]


def client_for(checks: Mapping[str, Check] | None = None, **kwargs: float) -> TestClient:
    app = FastAPI()
    app.include_router(health_router(checks, **kwargs))
    return TestClient(app)


async def passing() -> bool:
    return True


async def failing() -> bool:
    return False


async def raising() -> bool:
    raise ConnectionError("postgres injoignable")


async def hanging() -> bool:
    await asyncio.Event().wait()
    return True


def test_healthz_is_ok_without_running_any_check() -> None:
    calls: list[str] = []

    async def spy() -> bool:
        calls.append("called")
        raise AssertionError("la vivacité ne doit pas appeler les sondes")

    response = client_for({"postgres": spy}).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == []


def test_readyz_is_ready_when_all_checks_pass() -> None:
    response = client_for({"postgres": passing, "kafka": passing}).get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": True, "kafka": True}}


def test_readyz_is_ready_without_checks() -> None:
    response = client_for().get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


def test_readyz_is_unavailable_when_a_check_fails() -> None:
    response = client_for({"postgres": passing, "kafka": failing}).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"postgres": True, "kafka": False}}


def test_readyz_logs_and_fails_when_a_check_raises(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        response = client_for({"postgres": raising, "kafka": passing}).get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": False, "kafka": True}
    [record] = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert "postgres" in record.getMessage()
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], ConnectionError)


def test_readyz_fails_when_a_check_times_out(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        response = client_for({"mongo": hanging, "kafka": passing}, timeout_seconds=0.05).get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {"mongo": False, "kafka": True}
    assert any("mongo" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)


def test_readyz_reports_a_timeout_raised_by_the_check_as_an_error(caplog: pytest.LogCaptureFixture) -> None:
    async def connect_timeout() -> bool:
        raise TimeoutError("connexion postgres expirée")

    with caplog.at_level(logging.WARNING):
        response = client_for({"postgres": connect_timeout}, timeout_seconds=5.0).get("/readyz")

    assert response.status_code == 503
    [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert record.levelno == logging.ERROR, "erreur de la sonde, pas dépassement du délai de la route"
    assert record.exc_info is not None and isinstance(record.exc_info[1], TimeoutError)


def test_readyz_runs_checks_concurrently() -> None:
    # Chaque sonde attend que l'autre ait démarré : exécutées l'une après l'autre, la première expirerait.
    first_started, second_started = asyncio.Event(), asyncio.Event()

    async def first() -> bool:
        first_started.set()
        await second_started.wait()
        return True

    async def second() -> bool:
        second_started.set()
        await first_started.wait()
        return True

    response = client_for({"first": first, "second": second}, timeout_seconds=1.0).get("/readyz")

    assert response.status_code == 200
