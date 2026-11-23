from urllib.parse import quote

from market_order.adapters.dependencies import UNAVAILABLE, AttemptEvidence, Dependency
from market_order.domain.models import DependencyUnavailable, PaymentOutcome, Saga


class HttpInventory:
    def __init__(self, dependency: Dependency) -> None:
        self.dependency = dependency

    async def reserve(self, saga: Saga) -> bool:
        try:
            response = await self.dependency.post(
                "/v1/reservations",
                {
                    "order_id": saga.order_id,
                    "lines": [{"sku": item.sku, "quantity": item.quantity} for item in saga.lines],
                },
                {},
            )
        except UNAVAILABLE as error:
            raise DependencyUnavailable("Réservation indisponible") from error
        if response.status_code == 409:
            return False
        if response.status_code != 201:
            raise DependencyUnavailable("Réponse de réservation inexploitable")
        try:
            body = response.json()
        except ValueError as error:
            raise DependencyUnavailable("Corps de réservation inexploitable") from error
        if not isinstance(body, dict) or body.get("status") != "RESERVED":
            raise DependencyUnavailable("La réservation n'est pas dans l'état RESERVED")
        return True

    async def _finish(self, saga: Saga, operation: str) -> bool:
        try:
            response = await self.dependency.post(
                f"/v1/reservations/{quote(saga.order_id, safe='')}/{operation}", None, {}
            )
        except UNAVAILABLE:
            return False
        return response.status_code == 204

    async def confirm(self, saga: Saga) -> bool:
        return await self._finish(saga, "confirm")

    async def release(self, saga: Saga) -> bool:
        return await self._finish(saga, "release")


class HttpPayment:
    def __init__(self, dependency: Dependency, environment: str) -> None:
        self.dependency = dependency
        self.environment = environment

    async def pay(self, saga: Saga) -> PaymentOutcome:
        headers = {"Idempotency-Key": saga.order_id}
        if self.environment == "local" and saga.simulate_failure:
            headers["X-Simulate-Failure"] = "payment"
        evidence = AttemptEvidence()
        try:
            response = await self.dependency.post(
                "/v1/payments",
                {
                    "order_id": saga.order_id,
                    "amount": format(saga.total, ".2f"),
                    "currency": "GBP",
                },
                headers,
                evidence,
            )
        except UNAVAILABLE:
            return PaymentOutcome.UNKNOWN if evidence.uncertain else PaymentOutcome.NOT_SENT
        try:
            body = response.json()
            if response.status_code == 201 and body.get("status") == "CAPTURED" and body.get("payment_id"):
                return PaymentOutcome.CAPTURED
            if response.status_code == 402 and body.get("status") == "DECLINED":
                return PaymentOutcome.DECLINED
        except (ValueError, AttributeError):
            pass
        return PaymentOutcome.UNKNOWN
