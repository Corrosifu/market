from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from market_order.application.ports import Orders
from market_order.application.saga import OrderService
from market_order.domain.models import BodyMismatch, Conflict, InvalidOrder, Line, OwnershipLost
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/orders", tags=["orders"])


class OrderLine(BaseModel):
    sku: str = Field(min_length=1)
    quantity: int = Field(strict=True, ge=1, le=2147483647)


class OrderRequest(BaseModel):
    lines: list[OrderLine] = Field(min_length=1)


class OrderReply(BaseModel):
    id: str
    status: Literal["CONFIRMED", "CANCELLED"]


class UnavailableReply(BaseModel):
    id: str
    status: Literal["PENDING", "CANCELLED"]
    detail: str


class OrderView(BaseModel):
    id: str
    status: Literal["PENDING", "CONFIRMED", "CANCELLED"]
    lines: list[OrderLine]


def identity(x_user_id: Annotated[str | None, Header()] = None) -> str:
    if not x_user_id:
        raise HTTPException(401, "Identité requise")
    return x_user_id


@router.post(
    "",
    status_code=201,
    response_model=OrderReply,
    responses={
        400: {"description": "Clé requise"},
        401: {"description": "Identité requise"},
        409: {"description": "Commande en cours ou stock indisponible"},
        503: {"description": "Dépendance indisponible ou issue non établie", "model": UnavailableReply},
    },
)
async def create(
    body: OrderRequest,
    request: Request,
    customer: Annotated[str, Depends(identity)],
    idempotency_key: Annotated[str | None, Header()] = None,
    x_simulate_failure: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key requise")
    service = cast(OrderService, request.app.state.service)
    try:
        result = await service.create(
            customer,
            idempotency_key,
            tuple(Line(item.sku, item.quantity) for item in body.lines),
            x_simulate_failure == "payment",
        )
    except (BodyMismatch, InvalidOrder) as error:
        raise HTTPException(422, str(error)) from error
    except (Conflict, OwnershipLost) as error:
        raise HTTPException(409, "Commande en cours") from error
    return JSONResponse(status_code=result.code, content=result.body)


@router.get(
    "/{order_id}",
    response_model=OrderView,
    responses={
        401: {"description": "Identité requise"},
        404: {"description": "Commande inconnue"},
    },
)
async def get(
    order_id: str,
    request: Request,
    customer: Annotated[str, Depends(identity)],
    x_user_role: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    repository = cast(Orders, request.app.state.orders)
    order = await repository.get(order_id, customer, x_user_role == "ops")
    if order is None:
        raise HTTPException(404, "Commande inconnue")
    return order
