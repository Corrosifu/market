"""Chaque méthode libère sa connexion avant de rendre la main au service appelant."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from market_order.application.ports import Publisher
from market_order.domain.models import (
    BodyMismatch,
    Conflict,
    Line,
    OwnershipLost,
    Reason,
    Reply,
    Saga,
    Step,
    event,
    fingerprint,
)
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


class PostgresOrders:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def begin(
        self, customer_id: str, key: str, lines: tuple[Line, ...], total: Decimal, simulate_failure: bool
    ) -> Saga | Reply:
        saga = Saga(
            str(uuid4()), datetime.now(UTC), customer_id, lines, total, str(uuid4()), simulate_failure=simulate_failure
        )
        digest = fingerprint(lines)
        async with self.engine.begin() as connection:
            inserted = (
                (
                    await connection.execute(
                        text("""INSERT INTO orders.idempotency_keys
                (customer_id, key, fingerprint, order_id) VALUES (:customer, :key, :digest, :id)
                ON CONFLICT (customer_id, key) DO NOTHING RETURNING order_id"""),
                        {"customer": customer_id, "key": key, "digest": digest, "id": saga.order_id},
                    )
                )
                .mappings()
                .first()
            )
            if inserted is None:
                row = (
                    (
                        await connection.execute(
                            text("""SELECT fingerprint, response_code, response_body
                    FROM orders.idempotency_keys WHERE customer_id = :customer AND key = :key"""),
                            {"customer": customer_id, "key": key},
                        )
                    )
                    .mappings()
                    .one()
                )
                if row["fingerprint"] != digest:
                    raise BodyMismatch("La clé existe avec un autre corps")
                if row["response_code"] is None:
                    raise Conflict("Commande en cours")
                return Reply(int(row["response_code"]), dict(row["response_body"]))
            await connection.execute(
                text("""INSERT INTO orders.orders
                (id, ordered_at, customer_id, status, total_gbp)
                VALUES (:id, :at, :customer, 'PENDING', :total)"""),
                {"id": saga.order_id, "at": saga.ordered_at, "customer": customer_id, "total": total},
            )
            for line in lines:
                await connection.execute(
                    text("""INSERT INTO orders.order_lines
                    (id, order_id, sku, quantity, unit_price_gbp) VALUES (:id, :order, :sku, :q, :price)"""),
                    {
                        "id": str(uuid4()),
                        "order": saga.order_id,
                        "sku": line.sku,
                        "q": line.quantity,
                        "price": total / sum(item.quantity for item in lines),
                    },
                )
            await connection.execute(
                text("""INSERT INTO orders.saga_instances
                (order_id, ordered_at, step, owner, simulate_failure)
                VALUES (:id, :at, 'RESERVING', :owner, :simulate)"""),
                {"id": saga.order_id, "at": saga.ordered_at, "owner": saga.owner, "simulate": simulate_failure},
            )
        return saga

    async def checkpoint(self, saga: Saga, step: Step, reason: Reason | None = None, code: int | None = None) -> None:
        async with self.engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        text("""UPDATE orders.saga_instances
                SET step = :step, reason = :reason, response_code = :code, updated_at = clock_timestamp()
                WHERE order_id = :id AND owner = :owner AND step <> 'DONE' RETURNING order_id"""),
                        {
                            "step": step.value,
                            "reason": reason.value if reason else None,
                            "code": code,
                            "id": saga.order_id,
                            "owner": saga.owner,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise OwnershipLost(saga.order_id)
        saga.step, saga.reason, saga.response_code = step, reason, code

    async def remember(self, saga: Saga, reply: Reply) -> None:
        async with self.engine.begin() as connection:
            await self._remember(connection, saga, reply)

    async def _remember(self, connection: AsyncConnection, saga: Saga, reply: Reply) -> None:
        # La première réponse est immuable, y compris un 503 PENDING repris ensuite avec succès.
        await connection.execute(
            text("""UPDATE orders.idempotency_keys
            SET response_code = :code, response_body = CAST(:body AS JSONB)
            WHERE order_id = :id AND response_code IS NULL"""),
            {"id": saga.order_id, "code": reply.code, "body": json.dumps(reply.body)},
        )

    async def finish(self, saga: Saga, confirmed: bool, reason: Reason | None, reply: Reply) -> None:
        envelope = event(saga, confirmed, reason)
        async with self.engine.begin() as connection:
            owned = (
                (
                    await connection.execute(
                        text("""SELECT owner, step FROM orders.saga_instances
                WHERE order_id = :id FOR UPDATE"""),
                        {"id": saga.order_id},
                    )
                )
                .mappings()
                .first()
            )
            if owned is None or owned["owner"] != saga.owner:
                raise OwnershipLost(saga.order_id)
            if owned["step"] == "DONE":
                return
            changed = (
                (
                    await connection.execute(
                        text("""UPDATE orders.orders SET status = :status
                WHERE id = :id AND ordered_at = :at AND status = 'PENDING' RETURNING id"""),
                        {
                            "status": "CONFIRMED" if confirmed else "CANCELLED",
                            "id": saga.order_id,
                            "at": saga.ordered_at,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if changed is None:
                return
            await connection.execute(
                text("""UPDATE orders.saga_instances
                SET step = 'DONE', updated_at = clock_timestamp(), reason = :reason, response_code = :code
                WHERE order_id = :id AND owner = :owner"""),
                {
                    "id": saga.order_id,
                    "owner": saga.owner,
                    "reason": reason.value if reason else None,
                    "code": reply.code,
                },
            )
            await connection.execute(
                text("""INSERT INTO orders.outbox (event_id, order_id, payload)
                VALUES (:event_id, :id, CAST(:payload AS JSONB))"""),
                {"event_id": envelope["event_id"], "id": saga.order_id, "payload": json.dumps(envelope)},
            )
            await self._remember(connection, saga, reply)
        saga.step = Step.DONE

    async def get(self, order_id: str, customer_id: str, ops: bool) -> dict[str, object] | None:
        async with self.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("""SELECT id, status FROM orders.orders
                WHERE id = :id AND (customer_id = :customer OR :ops)
                ORDER BY ordered_at DESC LIMIT 1"""),
                        {"id": order_id, "customer": customer_id, "ops": ops},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            lines = await self._lines(connection, order_id)
            return {
                "id": str(row["id"]),
                "status": str(row["status"]),
                "lines": [{"sku": item.sku, "quantity": item.quantity} for item in lines],
            }

    async def _lines(self, connection: AsyncConnection, order_id: str) -> tuple[Line, ...]:
        rows = (
            (
                await connection.execute(
                    text("""SELECT sku, quantity FROM orders.order_lines
            WHERE order_id = :id ORDER BY id"""),
                    {"id": order_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(Line(str(row["sku"]), int(row["quantity"])) for row in rows)

    async def claim_stale(self, seconds: float, active: set[str]) -> Saga | None:
        async with self.engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        text("""SELECT order_id FROM orders.saga_instances
                WHERE step <> 'DONE' AND updated_at < clock_timestamp() - :seconds * interval '1 second'
                AND NOT (order_id = ANY(CAST(:active AS TEXT[])))
                ORDER BY updated_at LIMIT 1 FOR UPDATE SKIP LOCKED"""),
                        {"seconds": seconds, "active": list(active)},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            owner = str(uuid4())
            await connection.execute(
                text("""UPDATE orders.saga_instances SET owner = :owner,
                updated_at = clock_timestamp() WHERE order_id = :id"""),
                {"owner": owner, "id": row["order_id"]},
            )
            saga_row = (
                (
                    await connection.execute(
                        text("""SELECT o.id, o.ordered_at, o.customer_id,
                o.total_gbp, s.step, s.owner, s.simulate_failure, s.reason, s.response_code
                FROM orders.orders o JOIN orders.saga_instances s
                ON o.id = s.order_id AND o.ordered_at = s.ordered_at WHERE s.order_id = :id"""),
                        {"id": row["order_id"]},
                    )
                )
                .mappings()
                .one()
            )
            return await self._saga(connection, saga_row)

    async def _saga(self, connection: AsyncConnection, row: RowMapping) -> Saga:
        return Saga(
            str(row["id"]),
            row["ordered_at"],
            str(row["customer_id"]),
            await self._lines(connection, str(row["id"])),
            Decimal(row["total_gbp"]),
            str(row["owner"]),
            Step(row["step"]),
            bool(row["simulate_failure"]),
            Reason(row["reason"]) if row["reason"] else None,
            int(row["response_code"]) if row["response_code"] is not None else None,
        )

    async def relay_once(self, publisher: Publisher) -> bool:
        async with self.engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        text("""SELECT event_id, order_id, payload FROM orders.outbox
                WHERE published_at IS NULL ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED""")
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return False
            await publisher.send(str(row["order_id"]), dict(row["payload"]))
            await connection.execute(
                text("""UPDATE orders.outbox SET published_at = clock_timestamp()
                WHERE event_id = :id"""),
                {"id": row["event_id"]},
            )
        return True

    async def ready(self) -> bool:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM orders.saga_instances LIMIT 1"))
        return True
