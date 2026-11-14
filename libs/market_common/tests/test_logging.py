"""Comportement des journaux JSON : une ligne par événement, trace_id lu du contexte, timestamp UTC."""
from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from market_common.logging import (
    JsonFormatter,
    configure_logging,
    get_trace_id,
    set_trace_id,
    trace_id_context,
    trace_id_var,
)


@pytest.fixture
def capture() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(service_name="order"))
    logger = logging.getLogger("market.test.capture")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield logger, stream
    logger.handlers = []


@pytest.fixture
def clean_root() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    yield root
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_log_line_is_json_with_expected_fields_and_null_trace_id(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture

    logger.info("commande %s créée", "o-1")

    [event] = lines(stream)
    assert event["level"] == "INFO"
    assert event["service"] == "order"
    assert event["logger"] == "market.test.capture"
    assert event["message"] == "commande o-1 créée"
    assert event["trace_id"] is None
    stamp = datetime.fromisoformat(event["timestamp"])
    assert stamp.utcoffset() == timedelta(0)


def test_trace_id_from_context_appears_in_log_line(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture

    with trace_id_context("4bf92f3577b34da6a3ce929d0e0e4736"):
        logger.warning("dans la requête")
    logger.warning("hors requête")

    inside, outside = lines(stream)
    assert inside["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert outside["trace_id"] is None


def test_trace_id_context_restores_previous_value() -> None:
    token = set_trace_id("outer")
    try:
        with trace_id_context("inner"):
            assert get_trace_id() == "inner"
        assert get_trace_id() == "outer"
    finally:
        trace_id_var.reset(token)
    assert get_trace_id() is None


def test_exception_is_serialized_on_the_same_line(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture

    try:
        raise ValueError("stock négatif\nsur deux lignes")
    except ValueError:
        logger.exception("échec de réservation")

    assert len(stream.getvalue().splitlines()) == 1
    [event] = lines(stream)
    assert event["level"] == "ERROR"
    assert "ValueError: stock négatif" in event["exc_info"]


def test_configure_logging_is_idempotent(clean_root: logging.Logger, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("inventory", "DEBUG")
    configure_logging("inventory", "DEBUG")

    json_handlers = [h for h in clean_root.handlers if isinstance(h.formatter, JsonFormatter)]
    assert len(json_handlers) == 1
    assert clean_root.level == logging.DEBUG

    logging.getLogger("market.test.root").debug("une seule ligne")

    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e["message"] for e in out] == ["une seule ligne"]
    assert out[0]["service"] == "inventory"
