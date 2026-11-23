from uuid import uuid4

from market_payment.domain.model import Capture, Payment, Status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class PostgresPayments:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def capture(self, capture: Capture, status: Status) -> Payment:
        async with self.engine.begin() as connection:
            values = {
                "payment_id": str(uuid4()),
                "order_id": capture.order_id,
                "amount": capture.amount,
                "currency": capture.currency,
                "status": status.value,
            }
            row = (
                (
                    await connection.execute(
                        text("""INSERT INTO payment.payments
                (payment_id, order_id, payment_type, amount_gbp, currency, status, created_at)
                VALUES (:payment_id, :order_id, 'CAPTURE', :amount, :currency, :status, now())
                ON CONFLICT (order_id) WHERE payment_type = 'CAPTURE' AND provenance_kind IS NULL
                DO NOTHING RETURNING payment_id, status"""),
                        values,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                # Une insertion concurrente attend sa validation avant le conflit ; ce SELECT voit son résultat.
                row = (
                    (
                        await connection.execute(
                            text("""SELECT payment_id, status FROM payment.payments
                    WHERE order_id = :order_id AND payment_type = 'CAPTURE' AND provenance_kind IS NULL"""),
                            {"order_id": capture.order_id},
                        )
                    )
                    .mappings()
                    .one()
                )
            return Payment(str(row["payment_id"]), Status(row["status"]))

    async def ready(self) -> bool:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM payment.payments LIMIT 1"))
        return True
