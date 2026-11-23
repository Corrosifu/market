import copy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from market_order.application.saga import OrderService
from market_order.domain.models import (
    BodyMismatch,
    Conflict,
    Line,
    PaymentOutcome,
    Reason,
    Saga,
    Step,
    event,
    fingerprint,
)


class MemoryOrders:
    def __init__(self):
        self.keys = {}
        self.sagas = {}
        self.statuses = {}
        self.outbox = []
        self.clock = 0
        self.touched = {}

    async def begin(self, customer_id, key, lines, total, simulate_failure):
        identity = (customer_id, key)
        if identity in self.keys:
            digest, order_id, reply = self.keys[identity]
            if digest != fingerprint(lines):
                raise BodyMismatch()
            if reply is None:
                raise Conflict()
            return copy.deepcopy(reply)
        saga = Saga(
            str(uuid4()), datetime.now(UTC), customer_id, lines, total, "owner", simulate_failure=simulate_failure
        )
        self.keys[identity] = (fingerprint(lines), saga.order_id, None)
        self.sagas[saga.order_id] = copy.deepcopy(saga)
        self.statuses[saga.order_id] = "PENDING"
        self.touched[saga.order_id] = self.clock
        return saga

    async def checkpoint(self, saga, step, reason=None, code=None):
        saga.step, saga.reason, saga.response_code = step, reason, code
        self.sagas[saga.order_id] = copy.deepcopy(saga)
        self.touched[saga.order_id] = self.clock

    async def remember(self, saga, reply):
        for key, (digest, order_id, old) in self.keys.items():
            if order_id == saga.order_id and old is None:
                self.keys[key] = (digest, order_id, copy.deepcopy(reply))

    async def finish(self, saga, confirmed, reason, reply):
        if self.statuses[saga.order_id] != "PENDING":
            return
        self.statuses[saga.order_id] = "CONFIRMED" if confirmed else "CANCELLED"
        self.outbox.append(event(saga, confirmed, reason))
        await self.remember(saga, reply)
        await self.checkpoint(saga, Step.DONE)

    async def claim_stale(self, seconds, active):
        for order_id, saga in self.sagas.items():
            if saga.step != Step.DONE and order_id not in active and self.clock - self.touched[order_id] >= seconds:
                self.touched[order_id] = self.clock
                return copy.deepcopy(saga)
        return None


class Inventory:
    def __init__(self):
        self.calls = []
        self.fail_confirm = self.fail_release = False
        self.stock = True

    async def reserve(self, saga):
        self.calls.append("reserve")
        return self.stock

    async def confirm(self, saga):
        self.calls.append("confirm")
        return not self.fail_confirm

    async def release(self, saga):
        self.calls.append("release")
        return not self.fail_release


class Payment:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def pay(self, saga):
        self.calls.append(saga.order_id)
        return self.outcomes.pop(0)


def service(*outcomes):
    database, inventory, payment = MemoryOrders(), Inventory(), Payment(*outcomes)
    return OrderService(database, inventory, payment, Decimal("10.00"), 60), database, inventory, payment


LINES = (Line("sku", 2),)


@pytest.mark.anyio
async def test_saga_compensates_reservation_when_payment_is_declined():
    app, database, inventory, payment = service(PaymentOutcome.DECLINED)
    result = await app.create("client", "key", LINES, False)
    assert result.code == 201 and result.body["status"] == "CANCELLED"
    assert inventory.calls == ["reserve", "release"]
    assert database.outbox[0]["payload"]["reason"] == Reason.PAYMENT_DECLINED
    replay = await app.create("client", "key", LINES, False)
    assert replay == result and len(payment.calls) == 1 and len(database.outbox) == 1


@pytest.mark.anyio
async def test_body_mismatch_replay_has_no_inventory_effect():
    app, _, inventory, _ = service(PaymentOutcome.CAPTURED)
    await app.create("client", "key", LINES, False)
    before = inventory.calls.copy()
    with pytest.raises(BodyMismatch):
        await app.create("client", "key", (Line("other", 1),), False)
    assert inventory.calls == before


@pytest.mark.anyio
async def test_unknown_payment_outcome_keeps_order_pending_until_recovery():
    import asyncio

    import httpx
    from market_order.adapters.dependencies import Dependency
    from market_order.adapters.gateways import HttpPayment
    from market_order.config import Settings

    clock, captured, requests = [0.0], [False], []

    async def respond(request):
        requests.append(request)
        if not captured[0]:
            await asyncio.Event().wait()  # annulé par le vrai délai de market_common
        return httpx.Response(201, json={"status": "CAPTURED", "payment_id": "pay"})

    database, inventory = MemoryOrders(), Inventory()
    config = Settings.model_validate(
        {"ORDERS_DB_PASSWORD": "unit-only", "retry_attempts": 1, "breaker_failure_threshold": 1}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        dependency = Dependency("payment", "http://payment", 0.01, http, config, clock=lambda: clock[0])
        app = OrderService(database, inventory, HttpPayment(dependency, "local"), Decimal("10.00"), 60)
        result = await app.create("client", "key", LINES, False)
        assert result.code == 503 and result.body["status"] == "PENDING"
        assert inventory.calls == ["reserve"] and database.outbox == []
        order_id = result.body["id"]
        assert database.sagas[order_id].step == Step.PAYING
        captured[0], clock[0], database.clock = True, 6, 61
        assert await app.recover_once()
        assert database.statuses[order_id] == "CONFIRMED"
        assert inventory.calls == ["reserve", "confirm"]
        assert [r.headers["Idempotency-Key"] for r in requests] == [order_id, order_id]
        assert len(database.outbox) == 1 and database.outbox[0]["event_type"] == "OrderConfirmed"
        assert not await app.recover_once()
        assert await app.create("client", "key", LINES, False) == result


@pytest.mark.anyio
async def test_unknown_payment_is_never_compensated_when_recovery_cannot_connect():
    app, database, inventory, _ = service(PaymentOutcome.UNKNOWN, PaymentOutcome.NOT_SENT)
    result = await app.create("client", "key", LINES, False)
    database.clock = 61
    assert await app.recover_once()
    assert database.statuses[result.body["id"]] == "PENDING"
    assert inventory.calls == ["reserve"] and database.outbox == []


@pytest.mark.anyio
async def test_payment_known_not_sent_is_cancelled_only_after_release():
    app, database, inventory, _ = service(PaymentOutcome.NOT_SENT)
    inventory.fail_release = True
    pending = await app.create("client", "key", LINES, False)
    assert pending.code == 503 and pending.body["status"] == "PENDING"
    assert not database.outbox
    database.clock = 61
    inventory.fail_release = False
    await app.recover_once()
    assert database.statuses[pending.body["id"]] == "CANCELLED"
    assert len(database.outbox) == 1
    assert await app.create("client", "key", LINES, False) == pending


@pytest.mark.anyio
async def test_captured_payment_is_confirmed_on_recovery_never_released():
    app, database, inventory, payment = service(PaymentOutcome.CAPTURED)
    inventory.fail_confirm = True
    result = await app.create("client", "key", LINES, False)
    assert result.body["status"] == "PENDING" and database.outbox == []
    assert database.sagas[result.body["id"]].step == Step.CAPTURED
    database.clock = 61
    inventory.fail_confirm = False
    await app.recover_once()
    assert database.statuses[result.body["id"]] == "CONFIRMED"
    assert "release" not in inventory.calls and len(payment.calls) == 1


@pytest.mark.anyio
async def test_active_request_is_excluded_from_recovery_even_when_old():
    app, database, inventory, _ = service()
    saga = await database.begin("client", "key", LINES, Decimal("20.00"), False)
    database.clock = 1000
    app.active.add(saga.order_id)
    assert not await app.recover_once()
    assert inventory.calls == [] and database.outbox == []


@pytest.mark.anyio
async def test_inflight_key_is_visible_and_recovery_never_takes_active_request():
    import asyncio

    entered, proceed = asyncio.Event(), asyncio.Event()
    app, database, inventory, _ = service()

    class SlowPayment:
        async def pay(self, saga):
            entered.set()
            await proceed.wait()
            return PaymentOutcome.CAPTURED

    app.payment = SlowPayment()
    task = asyncio.create_task(app.create("client", "key", LINES, False))
    await entered.wait()
    with pytest.raises(Conflict):
        await app.create("client", "key", LINES, False)
    database.clock = 10000
    assert not await app.recover_once()
    assert inventory.calls == ["reserve"]
    proceed.set()
    result = await task
    assert result.body["status"] == "CONFIRMED" and len(database.outbox) == 1


@pytest.mark.anyio
async def test_released_reservation_replay_never_starts_payment():
    import httpx
    from market_order.adapters.dependencies import Dependency
    from market_order.adapters.gateways import HttpInventory
    from market_order.config import Settings

    app, database, _, payment = service(PaymentOutcome.CAPTURED)
    paths = []

    async def respond(request):
        paths.append(request.url.path)
        if request.url.path == "/v1/reservations":
            return httpx.Response(201, json={"status": "RELEASED"})
        assert request.url.path.endswith("/release")
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        config = Settings.model_validate({"ORDERS_DB_PASSWORD": "unit-only"})
        app.inventory = HttpInventory(Dependency("inventory", "http://inventory", 1, http, config))
        result = await app.create("client", "key", LINES, False)
    assert result.code == 503 and result.body["status"] == "CANCELLED"
    assert payment.calls == []
    assert len(paths) == 2 and paths[1].endswith("/release")
    assert len(database.outbox) == 1
    assert database.outbox[0]["event_type"] == "OrderCancelled"
