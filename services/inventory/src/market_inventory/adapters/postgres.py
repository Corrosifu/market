"""Réservations transactionnelles avec mise à jour conditionnelle côté PostgreSQL."""

from collections.abc import Sequence
from uuid import uuid4

from market_inventory.domain.model import (
    InsufficientStock,
    InvalidReservation,
    Line,
    Reservation,
    ReservationConflict,
    Status,
    Stock,
    UnknownReservation,
    normalize_lines,
)
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

RESERVE = text("""
UPDATE inventory.stock SET available = available - :q, reserved = reserved + :q, updated_at = now()
WHERE sku = :sku AND available >= :q
RETURNING product_id, seller_id, hub_id
""")
CONFIRM = text("""UPDATE inventory.stock SET reserved = reserved - :q, updated_at = now()
WHERE sku = :sku AND reserved >= :q RETURNING sku""")
RELEASE = text("""UPDATE inventory.stock SET reserved = reserved - :q, updated_at = now(), available = available + :q
WHERE sku = :sku AND reserved >= :q RETURNING sku""")
ROWS = text("""SELECT sku, quantity, status, product_id, seller_id, hub_id
FROM inventory.stock_reservations WHERE order_id = :order_id ORDER BY sku""")
MOVEMENT = text("""INSERT INTO inventory.inventory_movements
(movement_id, sku, product_id, seller_id, hub_id, movement_type, quantity_delta, occurred_at)
VALUES (:movement_id, :sku, :product_id, :seller_id, :hub_id, :movement_type, :delta, now())""")


def reservation(order_id: str, rows: Sequence[RowMapping]) -> Reservation:
    states = {Status(row["status"]) for row in rows}
    if len(states) != 1:
        raise ReservationConflict("États de réservation incohérents")
    return Reservation(order_id, states.pop(), tuple(Line(str(row["sku"]), int(row["quantity"])) for row in rows))


class PostgresInventory:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def _lock(self, connection: AsyncConnection, order_id: str) -> None:
        # Le seed exclusif attend la fin des mutations ; les commandes restent concurrentes entre elles.
        await connection.execute(text("SELECT pg_advisory_xact_lock_shared(hashtextextended('inventory:seed', 0))"))
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "inventory:order:" + order_id}
        )

    async def reserve(self, order_id: str, lines: tuple[Line, ...]) -> Reservation:
        if not order_id:
            raise InvalidReservation("Identifiant de commande requis")
        lines = normalize_lines(lines)
        async with self.engine.begin() as connection:
            await self._lock(connection, order_id)
            rows = (await connection.execute(ROWS, {"order_id": order_id})).mappings().all()
            if rows:
                existing = reservation(order_id, rows)
                if existing.lines != lines:
                    raise ReservationConflict("Commande déjà réservée avec des lignes différentes")
                return existing
            for line in lines:
                metadata = (await connection.execute(RESERVE, {"sku": line.sku, "q": line.quantity})).mappings().first()
                if metadata is None:
                    raise InsufficientStock(f"Stock insuffisant : {line.sku}")
                values = dict(metadata, reservation_id=str(uuid4()), order_id=order_id, sku=line.sku, q=line.quantity)
                await connection.execute(
                    text("""INSERT INTO inventory.stock_reservations
                    (reservation_id, order_id, sku, product_id, seller_id, hub_id, quantity, status, created_at)
                    VALUES (:reservation_id, :order_id, :sku, :product_id, :seller_id, :hub_id,
                            :q, 'RESERVED', now())"""),
                    values,
                )
                await connection.execute(
                    MOVEMENT, dict(values, movement_id=str(uuid4()), movement_type="RESERVE", delta=-line.quantity)
                )
        return Reservation(order_id, Status.RESERVED, lines)

    async def finish(self, order_id: str, status: Status) -> None:
        if status not in {Status.CONFIRMED, Status.RELEASED}:
            raise InvalidReservation("Transition terminale requise")
        async with self.engine.begin() as connection:
            await self._lock(connection, order_id)
            rows = (await connection.execute(ROWS, {"order_id": order_id})).mappings().all()
            if not rows:
                if status == Status.RELEASED:
                    return
                raise UnknownReservation(order_id)
            current = reservation(order_id, rows)
            if current.status == status:
                return
            if current.status != Status.RESERVED:
                raise ReservationConflict("Une réservation terminale ne peut pas être inversée")
            update = RELEASE if status == Status.RELEASED else CONFIRM
            for row in rows:
                values = dict(row, q=row["quantity"])
                changed = (await connection.execute(update, values)).mappings().first()
                if changed is None:
                    raise ReservationConflict("Compteur réservé incohérent")
                await connection.execute(
                    MOVEMENT,
                    dict(
                        values,
                        movement_id=str(uuid4()),
                        movement_type="RELEASE" if status == Status.RELEASED else "CONFIRM",
                        delta=int(row["quantity"]) if status == Status.RELEASED else -int(row["quantity"]),
                    ),
                )
            await connection.execute(
                text("UPDATE inventory.stock_reservations SET status = :status WHERE order_id = :order_id"),
                {"status": status.value, "order_id": order_id},
            )

    async def stock(self, sku: str) -> Stock | None:
        async with self.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("SELECT sku, available, reserved FROM inventory.stock WHERE sku = :sku"), {"sku": sku}
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else Stock(str(row["sku"]), int(row["available"]), int(row["reserved"]))

    async def ready(self) -> bool:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM inventory.stock LIMIT 1"))
        return True

    async def seed(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('inventory:seed', 0))"))
            skus = ("SKU-DEMO-1", "SKU-DEMO-2", "SKU-LAST-1")
            for sku, available in zip(skus, (100, 100, 1), strict=True):
                await connection.execute(
                    text("DELETE FROM inventory.stock_reservations WHERE sku = :sku"), {"sku": sku}
                )
                await connection.execute(
                    text("""INSERT INTO inventory.stock (sku, available, reserved, on_hand, updated_at)
                    VALUES (:sku, :available, 0, :available, now()) ON CONFLICT (sku) DO UPDATE
                    SET available = EXCLUDED.available, reserved = 0,
                        on_hand = EXCLUDED.on_hand, updated_at = now()"""),
                    {"sku": sku, "available": available},
                )
