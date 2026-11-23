from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from market_common import configure_logging, health_router

from market_inventory.adapters.postgres import PostgresInventory
from market_inventory.api.routes import router
from market_inventory.config import Settings, create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.model_validate({})
    configure_logging(settings.service_name, settings.log_level)
    engine = create_engine(settings)
    try:
        app.state.inventory = PostgresInventory(engine)
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Market Inventory", version="1.0.0", lifespan=lifespan)

    async def ready() -> bool:
        return await app.state.inventory.ready() is True

    app.include_router(health_router({"postgres": ready}))
    app.include_router(router)
    return app
