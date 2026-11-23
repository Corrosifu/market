from dataclasses import asdict
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Request, Response
from market_inventory.application.ports import Inventory
from market_inventory.domain.model import InvalidReservation, Line, ReservationConflict, Status, UnknownReservation
from pydantic import BaseModel, Field

router = APIRouter()


class ReservationLine(BaseModel):
    sku: str = Field(min_length=1)
    quantity: int = Field(strict=True, ge=1, le=2147483647)


class ReservationRequest(BaseModel):
    order_id: str = Field(min_length=1)
    lines: Annotated[list[ReservationLine], Field(min_length=1)]


class ReservationResponse(BaseModel):
    order_id: str
    status: Status
    lines: list[ReservationLine]


class StockResponse(BaseModel):
    sku: str
    available: int
    reserved: int


def repository(request: Request) -> Inventory:
    return cast(Inventory, request.app.state.inventory)


@router.post(
    "/v1/reservations",
    status_code=201,
    response_model=ReservationResponse,
    responses={409: {"description": "Stock insuffisant ou réservation incompatible"}},
)
async def reserve(body: ReservationRequest, request: Request) -> dict[str, object]:
    try:
        result = await repository(request).reserve(body.order_id, tuple(Line(x.sku, x.quantity) for x in body.lines))
    except InvalidReservation as error:
        raise HTTPException(422, str(error)) from error
    except ReservationConflict as error:
        raise HTTPException(409, str(error)) from error
    return asdict(result)


async def finish(order_id: str, status: Status, request: Request) -> Response:
    try:
        await repository(request).finish(order_id, status)
    except UnknownReservation as error:
        raise HTTPException(404, "Réservation inconnue") from error
    except ReservationConflict as error:
        raise HTTPException(409, str(error)) from error
    return Response(status_code=204)


@router.post(
    "/v1/reservations/{order_id}/confirm",
    status_code=204,
    responses={404: {"description": "Réservation inconnue"}, 409: {"description": "Déjà libérée"}},
)
async def confirm(order_id: str, request: Request) -> Response:
    return await finish(order_id, Status.CONFIRMED, request)


@router.post("/v1/reservations/{order_id}/release", status_code=204, responses={409: {"description": "Déjà confirmée"}})
async def release(order_id: str, request: Request) -> Response:
    return await finish(order_id, Status.RELEASED, request)


@router.get("/v1/inventory/{sku}", response_model=StockResponse, responses={404: {"description": "Stock inconnu"}})
async def stock(sku: str, request: Request) -> dict[str, object]:
    result = await repository(request).stock(sku)
    if result is None:
        raise HTTPException(404, "Stock inconnu")
    return asdict(result)
