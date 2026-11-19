"""Les journaux d'uvicorn (démarrage, accès) sortent en JSON, une ligne chacun, comme ceux du service."""
from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
from market_common import configure_logging, configure_uvicorn_logging

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture
def uvicorn_like_loggers() -> Iterator[io.StringIO]:
    """Reproduit la configuration par défaut d'uvicorn : gestionnaires texte propres, sans propagation."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved ={name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate) for name in UVICORN_LOGGERS}
    plain = io.StringIO()
    for name in ("uvicorn", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [logging.StreamHandler(plain)]
        logger.propagate = False
        logger.setLevel(logging.INFO)
    yield plain
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    for name, (handlers, propagate) in saved.items():
        logging.getLogger(name).handlers = handlers
        logging.getLogger(name).propagate = propagate


def test_uvicorn_records_go_through_the_json_handler_once(
    uvicorn_like_loggers: io.StringIO, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("catalog")
    configure_uvicorn_logging()
    configure_uvicorn_logging()

    logging.getLogger("uvicorn.error").info("Application startup complete.")
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "10.0.0.1:5000", "GET", "/healthz", "1.1", 200)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(e["logger"], e["message"], e["service"]) for e in events] == [
        ("uvicorn.error", "Application startup complete.", "catalog"),
        ("uvicorn.access", '10.0.0.1:5000 - "GET /healthz HTTP/1.1" 200', "catalog"),
    ]
    assert uvicorn_like_loggers.getvalue() == "", "plus aucune ligne texte hors JSON"
