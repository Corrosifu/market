"""Saga persistée, sans transaction de base traversant un appel sortant."""

import logging
from decimal import Decimal

from market_order.application.ports import Inventory, Orders, Payment
from market_order.domain.models import (
    DependencyUnavailable,
    InvalidOrder,
    Line,
    PaymentOutcome,
    Reason,
    Reply,
    Saga,
    Step,
)

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(
        self, orders: Orders, inventory: Inventory, payment: Payment, unit_price: Decimal, stuck_seconds: float
    ) -> None:
        self.orders, self.inventory, self.payment = orders, inventory, payment
        self.unit_price, self.stuck_seconds = unit_price, stuck_seconds
        # Le service est mono-worker : aucune reprise locale ne prend une requête encore active.
        self.active: set[str] = set()

    async def create(self, customer_id: str, key: str, lines: tuple[Line, ...], simulate: bool) -> Reply:
        total = sum(item.quantity for item in lines) * self.unit_price
        if not lines or total <= 0 or total > Decimal("9999999999.99"):
            raise InvalidOrder("Le montant doit tenir dans NUMERIC(12,2)")
        started = await self.orders.begin(customer_id, key, lines, total, simulate)
        if isinstance(started, Reply):
            return started
        self.active.add(started.order_id)
        try:
            return await self.drive(started, recovering=False)
        finally:
            self.active.discard(started.order_id)

    async def pending(self, saga: Saga) -> Reply:
        await self.orders.checkpoint(saga, saga.step, saga.reason, saga.response_code)
        reply = Reply(503, {"id": saga.order_id, "status": "PENDING", "detail": "Issue non établie ; reprise différée"})
        await self.orders.remember(saga, reply)
        logger.warning("saga en attente sans échéance garantie : order_id=%s step=%s", saga.order_id, saga.step)
        return reply

    async def cancel(self, saga: Saga, reason: Reason, code: int) -> Reply:
        await self.orders.checkpoint(saga, Step.RELEASING, reason, code)
        if not await self.inventory.release(saga):
            return await self.pending(saga)
        body: dict[str, object] = {"id": saga.order_id, "status": "CANCELLED"}
        if code != 201:
            body["detail"] = reason.value
        reply = Reply(code, body)
        await self.orders.finish(saga, False, reason, reply)
        return reply

    async def drive(self, saga: Saga, *, recovering: bool) -> Reply:
        if saga.step in (Step.RESERVING, Step.RESERVED) and recovering:
            # Aucun paiement n'a commencé : le checkpoint PAYING précède tout envoi.
            return await self.cancel(saga, Reason.RECOVERED_STUCK_SAGA, 503)
        if saga.step == Step.RESERVING:
            await self.orders.checkpoint(saga, Step.RESERVING)
            try:
                reserved = await self.inventory.reserve(saga)
            except DependencyUnavailable:
                return await self.cancel(saga, Reason.DEPENDENCY_UNAVAILABLE, 503)
            if not reserved:
                return await self.cancel(saga, Reason.STOCK_UNAVAILABLE, 409)
            await self.orders.checkpoint(saga, Step.RESERVED)
        if saga.step == Step.RESERVED:
            await self.orders.checkpoint(saga, Step.PAYING)
        if saga.step == Step.PAYING:
            outcome = await self.payment.pay(saga)
            if outcome == PaymentOutcome.CAPTURED:
                await self.orders.checkpoint(saga, Step.CAPTURED)
            elif outcome == PaymentOutcome.DECLINED:
                return await self.cancel(saga, Reason.PAYMENT_DECLINED, 201)
            elif outcome == PaymentOutcome.NOT_SENT and not recovering:
                return await self.cancel(saga, Reason.DEPENDENCY_UNAVAILABLE, 503)
            else:
                # En reprise, un refus de connexion ne réfute jamais une capture antérieure.
                return await self.pending(saga)
        if saga.step == Step.CAPTURED:
            if not await self.inventory.confirm(saga):
                return await self.pending(saga)
            reply = Reply(201, {"id": saga.order_id, "status": "CONFIRMED"})
            await self.orders.finish(saga, True, None, reply)
            return reply
        if saga.step == Step.RELEASING:
            return await self.cancel(saga, saga.reason or Reason.RECOVERED_STUCK_SAGA, saga.response_code or 503)
        raise ValueError("Saga déjà terminée")

    async def recover_once(self, excluded: set[str] | None = None) -> bool:
        saga = await self.orders.claim_stale(self.stuck_seconds, self.active | (excluded or set()))
        if saga is None:
            return False
        if excluded is not None:
            excluded.add(saga.order_id)
        self.active.add(saga.order_id)
        try:
            await self.drive(saga, recovering=True)
        finally:
            self.active.discard(saga.order_id)
        return True
