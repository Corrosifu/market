import asyncio
import copy
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from market_order.adapters.postgres import PostgresOrders
from market_order.domain.models import Line, Reply, Saga


class Rows:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class TransactionalDatabase:
    def __init__(self, fail_outbox=False):
        self.status = "PENDING"
        self.outbox = []
        self.published = False
        self.fail_outbox = fail_outbox
        self.in_transaction = False

    @asynccontextmanager
    async def begin(self):
        assert not self.in_transaction
        before = copy.deepcopy((self.status, self.outbox, self.published))
        self.in_transaction = True
        try:
            yield self
        except BaseException:
            self.status, self.outbox, self.published = before
            raise
        finally:
            self.in_transaction = False

    async def execute(self, statement, values=None):
        sql = " ".join(str(statement).split())
        assert self.in_transaction
        if sql.startswith("SELECT owner, step"):
            return Rows({"owner": "owner", "step": "RESERVING"})
        if sql.startswith("UPDATE orders.saga_instances"):
            return Rows({"order_id": "order"})
        if sql.startswith("UPDATE orders.orders"):
            if "status = 'PENDING'" in sql and self.status != "PENDING":
                return Rows()
            self.status = values["status"]
            return Rows({"id": "order"})
        if sql.startswith("INSERT INTO orders.outbox"):
            if self.fail_outbox:
                raise RuntimeError("écriture outbox refusée")
            self.outbox.append(values)
            return Rows()
        if sql.startswith("UPDATE orders.idempotency_keys"):
            return Rows()
        if sql.startswith("SELECT event_id"):
            assert "FOR UPDATE SKIP LOCKED" in sql
            return Rows({"event_id": "event", "order_id": "order", "payload": {"event_id": "event"}})
        if sql.startswith("UPDATE orders.outbox"):
            self.published = True
            return Rows()
        raise AssertionError(sql)


def saga():
    return Saga("order", datetime.now(UTC), "client", (Line("sku", 1),), Decimal("10.00"), "owner")


@pytest.mark.anyio
async def test_outbox_row_written_in_same_transaction_as_status_change():
    database = TransactionalDatabase(fail_outbox=True)
    repository = PostgresOrders(database)
    with pytest.raises(RuntimeError, match="outbox"):
        await repository.finish(saga(), True, None, Reply(201, {"id": "order", "status": "CONFIRMED"}))
    assert database.status == "PENDING"
    assert database.outbox == []


@pytest.mark.anyio
async def test_relay_marks_published_only_after_broker_ack():
    database = TransactionalDatabase()
    entered, ack = asyncio.Event(), asyncio.Event()

    class Publisher:
        async def send(self, order_id, event):
            assert order_id == "order"
            entered.set()
            await ack.wait()

    task = asyncio.create_task(PostgresOrders(database).relay_once(Publisher()))
    await entered.wait()
    assert not database.published
    ack.set()
    assert await task
    assert database.published


@pytest.mark.anyio
async def test_relay_failure_leaves_event_unpublished():
    database = TransactionalDatabase()

    class Publisher:
        async def send(self, order_id, event):
            raise RuntimeError("pas d’accusé de réception")

    with pytest.raises(RuntimeError):
        await PostgresOrders(database).relay_once(Publisher())
    assert not database.published


@pytest.mark.anyio
async def test_terminal_order_cannot_emit_another_terminal_event():
    database = TransactionalDatabase()
    database.status = "CONFIRMED"
    from market_order.domain.models import Reason

    await PostgresOrders(database).finish(
        saga(), False, Reason.DEPENDENCY_UNAVAILABLE, Reply(503, {"id": "order", "status": "CANCELLED"})
    )
    assert database.status == "CONFIRMED" and database.outbox == []
