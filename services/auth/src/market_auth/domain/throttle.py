"""Fenêtre glissante des échecs par e-mail, avec horloge monotone injectable."""
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable

from market_auth.domain.identity import LoginThrottled


class FailureLimiter:
    def __init__(
        self, max_failures: int, window_seconds: float, clock: Callable[[], float] = time.monotonic,
        *, max_keys: int = 10000,
    ) -> None:
        if max_failures < 1 or window_seconds <= 0 or max_keys < 1:
            raise ValueError("La fenêtre et le nombre d'échecs doivent être positifs")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.clock = clock
        self.max_keys = max_keys
        self.failures: OrderedDict[str, deque[float]] = OrderedDict()
        self.next_cleanup = clock()

    def check(self, email: str) -> None:
        now = self.clock()
        if now >= self.next_cleanup:
            for key in list(self.failures):
                self._prune(key, now)
            self.next_cleanup = now + self.window_seconds
        self._prune(email, now)
        attempts = self.failures.get(email)
        if attempts is not None and len(attempts) >= self.max_failures:
            raise LoginThrottled(max(1, math.ceil(attempts[0] + self.window_seconds - now)))

    def failed(self, email: str) -> None:
        if email not in self.failures and len(self.failures) >= self.max_keys:
            self.failures.popitem(last=False)
        self.failures.setdefault(email, deque()).append(self.clock())
        self.failures.move_to_end(email)

    def succeeded(self, email: str) -> None:
        self.failures.pop(email, None)

    def _prune(self, email: str, now: float) -> None:
        attempts = self.failures.get(email)
        if attempts is None:
            return
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        if not attempts:
            del self.failures[email]
