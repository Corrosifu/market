"""Un service assemble ses fondations uniquement depuis `market_common`, sans connaître les sous-modules."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def clean_root() -> Iterator[None]:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def test_service_wires_settings_logging_and_health_from_the_package(
    clean_root: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import market_common as mc

    monkeypatch.setenv("SERVICE_NAME", "payment")
    settings = mc.BaseServiceSettings()
    mc.configure_logging(settings.service_name, settings.log_level)
    app = FastAPI()
    app.include_router(mc.health_router())

    with mc.trace_id_context("abc123"):
        logging.getLogger("market.payment").info("démarré")

    assert TestClient(app).get("/healthz").status_code == 200
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    [event] = [e for e in events if e["logger"] == "market.payment"]
    assert (event["service"], event["trace_id"], mc.get_trace_id()) == ("payment", "abc123", None)
