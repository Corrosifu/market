from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from market_order.adapters.dependencies import Dependency
from market_order.adapters.gateways import HttpInventory
from market_order.config import Settings
from market_order.domain.models import DependencyUnavailable, Line, Saga


async def reserve(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as http:
        config = Settings.model_validate({"ORDERS_DB_PASSWORD": "unit-only"})
        gateway = HttpInventory(Dependency("inventory", "http://inventory", 1, http, config))
        saga = Saga("order", datetime.now(UTC), "client", (Line("sku", 1),), Decimal("10.00"), "owner")
        return await gateway.reserve(saga)


@pytest.mark.anyio
async def test_reserve_accepts_only_reserved_state():
    assert await reserve(httpx.Response(201, json={"status": "RESERVED"}))


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["RELEASED", "CONFIRMED"])
async def test_reserve_rejects_terminal_reservation_replays(status):
    with pytest.raises(DependencyUnavailable):
        await reserve(httpx.Response(201, json={"status": status}))


@pytest.mark.anyio
@pytest.mark.parametrize("content", [b"{}", b"[]", b"not-json"])
async def test_reserve_rejects_unusable_reservation_body(content):
    with pytest.raises(DependencyUnavailable):
        await reserve(httpx.Response(201, content=content))
