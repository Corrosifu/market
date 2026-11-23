from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from market_payment.application.ports import Payments
from market_payment.domain.model import Capture, Status, outcome
from pydantic import BaseModel, Field

router = APIRouter()


class PaymentRequest(BaseModel):
    order_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class CapturedResponse(BaseModel):
    payment_id: str
    status: Literal["CAPTURED"]


class DeclinedResponse(BaseModel):
    status: Literal["DECLINED"]


@router.post(
    "/v1/payments",
    status_code=201,
    response_model=CapturedResponse,
    responses={402: {"description": "Paiement refusé", "model": DeclinedResponse}},
)
async def capture(
    body: PaymentRequest,
    request: Request,
    idempotency_key: Annotated[str, Header()],
    x_simulate_failure: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    if idempotency_key != body.order_id:
        raise HTTPException(422, "Idempotency-Key doit correspondre à order_id")
    payments = cast(Payments, request.app.state.payments)
    payment = await payments.capture(
        Capture(body.order_id, body.amount, body.currency),
        outcome(str(request.app.state.environment), x_simulate_failure),
    )
    if payment.status == Status.DECLINED:
        return JSONResponse(status_code=402, content={"status": payment.status})
    return JSONResponse(status_code=201, content={"payment_id": payment.payment_id, "status": payment.status})
