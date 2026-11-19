"""Journaux JSON, une ligne par événement, avec le `trace_id` de la requête en cours.

Le `trace_id` vit dans un `contextvar` : chaque requête ou tâche asyncio a sa propre valeur.
OpenTelemetry le remplira quand le traçage sera branché ; d'ici là, le service le pose lui-même.
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def get_trace_id() -> str | None:
    return trace_id_var.get()


def set_trace_id(trace_id: str | None) -> Token[str | None]:
    """Pose le `trace_id` courant ; le jeton rendu permet de restaurer la valeur précédente (`trace_id_var.reset`)."""
    return trace_id_var.set(trace_id)


@contextmanager
def trace_id_context(trace_id: str | None) -> Iterator[None]:
    """Pose le `trace_id` le temps du bloc, puis restaure la valeur précédente."""
    token = trace_id_var.set(trace_id)
    try:
        yield
    finally:
        trace_id_var.reset(token)


class JsonFormatter(logging.Formatter):
    """Formate un enregistrement en un objet JSON sur une seule ligne."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id_var.get(),
        }
        if record.exc_info:
            event["exc_info"] = self.formatException(record.exc_info)
        # json.dumps échappe les retours à la ligne : une trace d'exception reste sur une seule ligne.
        return json.dumps(event, ensure_ascii=False, default=str)


def configure_logging(service_name: str, level: str | int = "INFO") -> None:
    """Installe un seul gestionnaire JSON sur la sortie standard du logger racine.

    Idempotente : un nouvel appel remplace le gestionnaire JSON existant au lieu d'en ajouter un second.
    """
    root = logging.getLogger()
    for existing in [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]:
        root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    root.addHandler(handler)
    root.setLevel(level.upper() if isinstance(level, str) else level)


UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_uvicorn_logging() -> None:
    """Fait passer les journaux d'uvicorn (démarrage, accès) par le gestionnaire JSON du logger racine.

    uvicorn installe ses propres gestionnaires texte, sans propagation, avant de charger l'application : on les
    retire et on rétablit la propagation. À appeler après `configure_logging`, au chargement de l'application
    (fabrique `uvicorn --factory`). Idempotente.
    """
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
