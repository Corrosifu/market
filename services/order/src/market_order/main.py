import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import httpx
from fastapi import FastAPI
from market_common import configure_logging, configure_uvicorn_logging, health_router

from market_order.adapters.dependencies import Dependency
from market_order.adapters.gateways import HttpInventory, HttpPayment
from market_order.adapters.kafka import KafkaPublisher
from market_order.adapters.postgres import PostgresOrders
from market_order.api.routes import router
from market_order.application.saga import OrderService
from market_order.config import Settings, create_engine

logger = logging.getLogger(__name__)


async def periodic(stop: asyncio.Event, interval: float, operation: Callable[[], Awaitable[None]]) -> None:
    while not stop.is_set():
        try:
            await operation()
        except Exception:
            logger.exception("traitement de fond en échec ; nouvel essai au prochain tour")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.model_validate({})
    configure_logging(settings.service_name, settings.log_level)
    configure_uvicorn_logging()
    engine = create_engine(settings)
    http = httpx.AsyncClient(trust_env=False)
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers, settings.kafka_delivery_timeout_seconds)
    repository = PostgresOrders(engine)
    service = OrderService(
        repository,
        HttpInventory(
            Dependency("inventory", settings.inventory_url, settings.inventory_timeout_seconds, http, settings)
        ),
        HttpPayment(
            Dependency("payment", settings.payment_url, settings.payment_timeout_seconds, http, settings),
            settings.environment,
        ),
        settings.order_stub_unit_price_gbp,
        settings.saga_stuck_seconds,
    )
    app.state.orders, app.state.service = repository, service
    stop = asyncio.Event()

    async def recover() -> None:
        seen: set[str] = set()
        while not stop.is_set() and await service.recover_once(seen):
            pass  # chaque saga au plus une fois par tour, même si elle reste PENDING

    async def relay() -> None:
        while not stop.is_set() and await repository.relay_once(publisher):
            pass

    tasks = [
        asyncio.create_task(periodic(stop, settings.saga_recovery_interval_seconds, recover)),
        asyncio.create_task(periodic(stop, settings.outbox_poll_seconds, relay)),
    ]
    try:
        yield
    finally:
        stop.set()
        # Laisser le travail synchrone Kafka terminer avant de libérer connexion et producteur.
        await asyncio.gather(*tasks, return_exceptions=True)
        await publisher.close()
        await http.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Market Order", version="1.0.0", lifespan=lifespan)

    async def ready() -> bool:
        return await cast(PostgresOrders, app.state.orders).ready()

    app.include_router(health_router({"postgres": ready}))
    app.include_router(router)
    return app


app = create_app()
