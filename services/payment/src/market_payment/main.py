from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from market_common import configure_logging, health_router

from market_payment.adapters.postgres import PostgresPayments
from market_payment.api.routes import router
from market_payment.config import Settings, create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.model_validate({})
    configure_logging(settings.service_name, settings.log_level)
    engine = create_engine(settings)
    try:
        app.state.payments = PostgresPayments(engine)
        app.state.environment = settings.environment
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Market Payment", version="1.0.0", lifespan=lifespan)

    async def ready() -> bool:
        return await app.state.payments.ready() is True

    app.include_router(health_router({"postgres": ready}))
    app.include_router(router)
    return app
