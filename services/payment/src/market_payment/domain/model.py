from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Status(StrEnum):
    CAPTURED = "CAPTURED"
    DECLINED = "DECLINED"


@dataclass(frozen=True)
class Payment:
    payment_id: str
    status: Status


@dataclass(frozen=True)
class Capture:
    order_id: str
    amount: Decimal
    currency: str


def outcome(environment: str, simulate_failure: str | None) -> Status:
    return Status.DECLINED if environment == "local" and simulate_failure == "payment" else Status.CAPTURED
