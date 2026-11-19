"""Argon2id avec vérification factice et concurrence mémoire bornée."""
import asyncio
import secrets
from collections.abc import Callable
from functools import partial
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from market_auth.domain.identity import HashSaturated


class ArgonPasswords:
    def __init__(
        self, concurrency: int = 2, *, max_waiting: int = 16,
        wait_timeout_seconds: float = 0.25, retry_after_seconds: int = 1,
    ) -> None:
        if concurrency < 1 or max_waiting < 0 or wait_timeout_seconds <= 0 or retry_after_seconds < 1:
            raise ValueError("Capacité, délai et Retry-After de hachage invalides")
        self._hasher = PasswordHasher()
        self._dummy = self._hasher.hash(secrets.token_urlsafe(32))
        self._slots = asyncio.Semaphore(concurrency)
        self._capacity = concurrency + max_waiting
        self._admitted = 0
        self._wait_timeout = wait_timeout_seconds
        self._retry_after = retry_after_seconds
        self._jobs: set[asyncio.Task[Any]] = set()

    async def hash(self, password: str) -> str:
        return await self._run(partial(self._hasher.hash, password))

    async def verify(self, password_hash: str | None, password: str) -> bool:
        valid = await self._run(partial(self._verify, password_hash or self._dummy, password))
        return valid and password_hash is not None

    async def _run[T](self, operation: Callable[[], T]) -> T:
        # Compter avant le premier await borne aussi les acquisitions concurrentes.
        if self._admitted >= self._capacity:
            raise HashSaturated(self._retry_after)
        self._admitted += 1
        try:
            try:
                await asyncio.wait_for(self._slots.acquire(), timeout=self._wait_timeout)
            except TimeoutError:
                raise HashSaturated(self._retry_after) from None
        except BaseException:
            self._admitted -= 1
            raise
        job = asyncio.create_task(asyncio.to_thread(operation))
        self._jobs.add(job)
        job.add_done_callback(self._finished)
        # Annuler une requête ne peut pas arrêter Argon2 dans son thread.
        # La capacité reste occupée jusqu'au callback de fin réelle.
        return await asyncio.shield(job)

    def _finished(self, job: asyncio.Task[Any]) -> None:
        self._jobs.remove(job)
        self._slots.release()
        self._admitted -= 1
        if not job.cancelled():
            job.exception()  # Récupérer aussi une erreur si la requête a été annulée.

    def _verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerificationError:
            return False
