"""Connexion et ports des adaptateurs du service."""
import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from market_auth.domain.identity import InvalidCredentials, Principal, User, normalize_email
from market_auth.domain.throttle import FailureLimiter


class Users(Protocol):
    async def by_email(self, email: str) -> User | None: ...

    async def upsert(self, users: list[User]) -> None: ...


class Passwords(Protocol):
    async def verify(self, password_hash: str | None, password: str) -> bool: ...

    async def hash(self, password: str) -> str: ...


class Tokens(Protocol):
    def issue(self, principal: Principal) -> str: ...


@dataclass
class _EmailLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class LoginService:
    def __init__(self, users: Users, passwords: Passwords, tokens: Tokens, limiter: FailureLimiter) -> None:
        self.users = users
        self.passwords = passwords
        self.tokens = tokens
        self.limiter = limiter
        self._locks: dict[str, _EmailLock] = {}

    async def login(self, email: str, password: str) -> str:
        email = normalize_email(email)
        # Sérialiser une même clé empêche une rafale concurrente de dépasser le seuil.
        state = self._locks.setdefault(email, _EmailLock())
        state.users += 1
        try:
            async with state.lock:
                self.limiter.check(email)
                user = await self.users.by_email(email)
                valid = await self.passwords.verify(user.password_hash if user else None, password)
                if not valid or user is None:
                    self.limiter.failed(email)
                    raise InvalidCredentials
                self.limiter.succeeded(email)
                return self.tokens.issue(user.principal)
        finally:
            state.users -= 1
            if state.users == 0:
                del self._locks[email]
