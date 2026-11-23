import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4


class Step(StrEnum):
    RESERVING = "RESERVING"
    RESERVED = "RESERVED"
    PAYING = "PAYING"
    CAPTURED = "CAPTURED"
    RELEASING = "RELEASING"
    DONE = "DONE"


class PaymentOutcome(StrEnum):
    CAPTURED = "CAPTURED"
    DECLINED = "DECLINED"
    NOT_SENT = "NOT_SENT"
    UNKNOWN = "UNKNOWN"


class DependencyUnavailable(Exception):
    pass


class InvalidOrder(ValueError):
    pass


class Reason(StrEnum):
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    STOCK_UNAVAILABLE = "STOCK_UNAVAILABLE"
    RECOVERED_STUCK_SAGA = "RECOVERED_STUCK_SAGA"


class Conflict(Exception):
    pass


class BodyMismatch(Exception):
    pass


class OwnershipLost(Exception):
    pass


@dataclass(frozen=True)
class Line:
    sku: str
    quantity: int


@dataclass(frozen=True)
class Reply:
    code: int
    body: dict[str, object]


@dataclass
class Saga:
    order_id: str
    ordered_at: datetime
    customer_id: str
    lines: tuple[Line, ...]
    total: Decimal
    owner: str
    step: Step = Step.RESERVING
    simulate_failure: bool = False
    reason: Reason | None = None
    response_code: int | None = None


def fingerprint(lines: tuple[Line, ...]) -> str:
    # L'ordre et les doublons du corps font partie de l'empreinte.
    value = [{"sku": line.sku, "quantity": line.quantity} for line in lines]
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def event(saga: Saga, confirmed: bool, reason: Reason | None) -> dict[str, object]:
    payload: dict[str, object] = {"order_id": saga.order_id}
    if confirmed:
        payload.update(
            customer_id=saga.customer_id,
            lines=[{"sku": line.sku, "quantity": line.quantity} for line in saga.lines],
            total_gbp=format(saga.total, ".2f"),
        )
    else:
        if reason is None:
            raise ValueError("Une annulation exige un motif")
        payload["reason"] = reason.value
    return {
        "event_id": str(uuid4()),
        "event_type": "OrderConfirmed" if confirmed else "OrderCancelled",
        "occurred_at": datetime.now(UTC).isoformat(),
        "schema_version": 1,
        "payload": payload,
    }
