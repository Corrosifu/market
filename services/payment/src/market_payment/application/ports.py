from typing import Protocol

from market_payment.domain.model import Capture, Payment, Status


class Payments(Protocol):
    async def capture(self, capture: Capture, status: Status) -> Payment: ...

    async def ready(self) -> bool: ...
