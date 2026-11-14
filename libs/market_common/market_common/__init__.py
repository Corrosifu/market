"""Mécanismes techniques partagés (réglages, journaux, traces, résilience). Aucune règle métier."""
from market_common.health import HealthCheck, health_router
from market_common.logging import (
    JsonFormatter,
    configure_logging,
    get_trace_id,
    set_trace_id,
    trace_id_context,
    trace_id_var,
)
from market_common.settings import BaseServiceSettings

__all__ = [
    "BaseServiceSettings",
    "HealthCheck",
    "JsonFormatter",
    "configure_logging",
    "get_trace_id",
    "health_router",
    "set_trace_id",
    "trace_id_context",
    "trace_id_var",
]
