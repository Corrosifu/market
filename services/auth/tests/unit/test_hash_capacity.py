import asyncio
import threading
import time

import httpx
import pytest
from market_auth.adapters.passwords import ArgonPasswords
from market_auth.application.login import LoginService
from market_auth.domain.throttle import FailureLimiter
from market_auth.main import create_app


@pytest.fixture
async def blocked_verifier(monkeypatch):
    release = threading.Event()
    started = asyncio.Queue()
    loop = asyncio.get_running_loop()
    counts = {"active": 0, "maximum": 0}
    lock = threading.Lock()

    def verify(self, encoded, password):
        with lock:
            counts["active"] += 1
            counts["maximum"] = max(counts["maximum"], counts["active"])
        loop.call_soon_threadsafe(started.put_nowait, None)
        try:
            assert release.wait(3), "Le test doit libérer le hachage bloqué"
            return False
        finally:
            with lock:
                counts["active"] -= 1

    monkeypatch.setattr(ArgonPasswords, "_verify", verify)
    yield release, started, counts
    release.set()


@pytest.mark.anyio
async def test_saturation_returns_503_with_retry_after_within_configured_deadline(users, tokens, blocked_verifier):
    release, started, _ = blocked_verifier
    passwords = ArgonPasswords(concurrency=1, max_waiting=1, wait_timeout_seconds=0.03, retry_after_seconds=2)
    app = create_app()
    app.state.login = LoginService(users, passwords, tokens, FailureLimiter(10, 300))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = asyncio.create_task(client.post("/v1/auth/login", json={"email": "one", "password": "wrong"}))
        try:
            await asyncio.wait_for(started.get(), 1)
            before = time.monotonic()
            response = await asyncio.wait_for(
                client.post("/v1/auth/login", json={"email": "two", "password": "wrong"}), 0.5,
            )
            assert response.status_code == 503
            assert response.headers["retry-after"] == "2"
            assert response.headers["cache-control"] == "no-store"
            assert time.monotonic() - before < 0.5
            assert "two" not in app.state.login.limiter.failures
        finally:
            release.set()
            assert (await first).status_code == 401
        assert (await client.post("/v1/auth/login", json={"email": "three", "password": "wrong"})).status_code == 401


@pytest.mark.anyio
async def test_hash_queue_refuses_overflow_before_wait_timeout(blocked_verifier):
    from market_auth.domain.identity import HashSaturated

    release, started, _ = blocked_verifier
    passwords = ArgonPasswords(concurrency=1, max_waiting=1, wait_timeout_seconds=2)
    first = asyncio.create_task(passwords.verify(None, "wrong"))
    queued = None
    try:
        await asyncio.wait_for(started.get(), 1)
        queued = asyncio.create_task(passwords.verify(None, "wrong"))
        await asyncio.sleep(0)  # Laisser la deuxième tâche entrer dans la file.
        with pytest.raises(HashSaturated):
            await asyncio.wait_for(passwords.verify(None, "wrong"), 0.2)
        assert not queued.done()
    finally:
        release.set()
        await first
        if queued is not None:
            await queued


@pytest.mark.anyio
async def test_hash_concurrency_is_respected_and_slots_recover(blocked_verifier):
    release, started, counts = blocked_verifier
    passwords = ArgonPasswords(concurrency=2, max_waiting=4, wait_timeout_seconds=2)
    tasks = [asyncio.create_task(passwords.verify(None, "wrong")) for _ in range(6)]
    try:
        await asyncio.wait_for(started.get(), 1)
        await asyncio.wait_for(started.get(), 1)
        assert counts["active"] == counts["maximum"] == 2
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(started.get(), 0.05)
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert counts["active"] == 0 and counts["maximum"] == 2
    assert not await passwords.verify(None, "wrong")


@pytest.mark.anyio
async def test_cancelling_a_running_hash_keeps_slot_until_thread_finishes(blocked_verifier):
    from market_auth.domain.identity import HashSaturated

    release, started, counts = blocked_verifier
    passwords = ArgonPasswords(concurrency=1, max_waiting=0, wait_timeout_seconds=1)
    first = asyncio.create_task(passwords.verify(None, "wrong"))
    try:
        await asyncio.wait_for(started.get(), 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(HashSaturated):
            await passwords.verify(None, "wrong")
    finally:
        release.set()
    # Attendre la fin réelle du thread, pas seulement celle de la requête annulée.
    async with asyncio.timeout(1):
        while passwords._jobs:
            await asyncio.sleep(0.001)
    assert not await passwords.verify(None, "wrong")
    assert counts["maximum"] == 1


@pytest.mark.anyio
async def test_hash_error_releases_capacity(monkeypatch):
    passwords = ArgonPasswords(concurrency=1, max_waiting=0)

    def broken(self, encoded, password):
        raise RuntimeError("Échec de test du hachage")

    monkeypatch.setattr(ArgonPasswords, "_verify", broken)
    with pytest.raises(RuntimeError, match="Échec de test"):
        await passwords.verify(None, "wrong")
    monkeypatch.setattr(ArgonPasswords, "_verify", lambda *args: False)
    assert not await passwords.verify(None, "wrong")
