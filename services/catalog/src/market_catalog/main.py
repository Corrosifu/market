"""Assemblage du service catalogue : `uvicorn --factory market_catalog.main:create_app`."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from market_common import configure_logging, configure_uvicorn_logging, health_router
from pymongo.monitoring import CommandListener

from market_catalog.adapters.mongo import open_catalog
from market_catalog.api import rest
from market_catalog.api.graphql import graphql_router
from market_catalog.application.fixtures import load_fixtures_if_empty
from market_catalog.domain.model import (
    CatalogError,
    InvalidRequest,
    NotASeller,
    ProductRejected,
    UnknownCategory,
    UnknownSeller,
)
from market_catalog.settings import CatalogSettings

logger = logging.getLogger(__name__)

STATUS_OF: dict[type[CatalogError], int] = {
    InvalidRequest: 422,
    UnknownCategory: 422,
    ProductRejected: 422,
    NotASeller: 403,
    UnknownSeller: 403,
}


async def _catalog_error(_: Request, exc: Exception) -> JSONResponse:
    code = next((c for kind, c in STATUS_OF.items() if isinstance(exc, kind)), 400)
    return JSONResponse(status_code=code, content={"detail": str(exc)})


def create_app(settings: CatalogSettings | None = None, *,
               event_listeners: Sequence[CommandListener] = ()) -> FastAPI:
    """`event_listeners` : écouteurs de commandes pymongo (les tests comptent ainsi les requêtes réelles)."""
    settings = settings or CatalogSettings()  # type: ignore[call-arg]  # MONGO_URL lu de l'environnement
    configure_logging(settings.service_name, settings.log_level)
    configure_uvicorn_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with open_catalog(settings.mongo_url.get_secret_value(), event_listeners=event_listeners) as opened:
            catalog, schemas = opened
            await load_fixtures_if_empty(catalog, environment=settings.environment)
            app.state.catalog = catalog
            app.state.categories = frozenset(schemas)
            yield

    app = FastAPI(title="Market catalog", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(CatalogError, _catalog_error)

    async def mongo_ready() -> bool:
        return bool(await app.state.catalog.ping())

    app.include_router(health_router({"mongo": mongo_ready}))
    app.include_router(rest.router)
    app.include_router(graphql_router())
    return app
