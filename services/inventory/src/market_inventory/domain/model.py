"""États et validation du stock, indépendants de la base et du transport."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class InvalidReservation(ValueError):
    pass


class ReservationConflict(Exception):
    pass


class InsufficientStock(ReservationConflict):
    pass


class UnknownReservation(Exception):
    pass


@dataclass(frozen=True)
class Line:
    sku: str
    quantity: int


@dataclass(frozen=True)
class Reservation:
    order_id: str
    status: Status
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class Stock:
    sku: str
    available: int
    reserved: int


def normalize_lines(lines: Sequence[Line]) -> tuple[Line, ...]:
    if not lines:
        raise InvalidReservation("Au moins une ligne est requise")
    quantities: dict[str, int] = {}
    for line in lines:
        if not line.sku or type(line.quantity) is not int or line.quantity < 1:
            raise InvalidReservation("SKU non vide et quantité entière positive requis")
        quantities[line.sku] = quantities.get(line.sku, 0) + line.quantity
        if quantities[line.sku] > 2147483647:
            raise InvalidReservation("Quantité hors de la capacité INTEGER de PostgreSQL")
    return tuple(Line(sku, quantity) for sku, quantity in sorted(quantities.items()))
