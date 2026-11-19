import asyncio

import pytest
from argon2.exceptions import VerifyMismatchError
from market_auth.application.login import LoginService
from market_auth.domain.identity import InvalidCredentials, LoginThrottled
from market_auth.domain.throttle import FailureLimiter


@pytest.fixture
def service(users, passwords, tokens):
    return LoginService(users, passwords, tokens, FailureLimiter(10, 300))


@pytest.mark.anyio
async def test_known_wrong_and_unknown_use_argon_and_same_error(service, client_user, passwords, monkeypatch):
    checked = []

    def verify(self, encoded, password):
        checked.append(encoded)
        raise VerifyMismatchError

    monkeypatch.setattr(type(passwords._hasher), "verify", verify)
    for email in (client_user.email, "unknown@market.test"):
        with pytest.raises(InvalidCredentials):
            await service.login(email, "wrong")
    assert len(checked) == 2
    assert checked[0] == client_user.password_hash
    assert checked[1] == passwords._dummy


@pytest.mark.anyio
@pytest.mark.parametrize("email", ["client@market.test", "unknown@market.test"])
async def test_ten_failures_throttle_normalized_email_only(service, client_user, email, tokens):
    for _ in range(10):
        with pytest.raises(InvalidCredentials):
            await service.login(email, "wrong")
    with pytest.raises(LoginThrottled) as failure:
        await service.login(" " + email.upper() + " ", "wrong")
    assert 1 <= failure.value.retry_after <= 300
    if email != client_user.email:
        assert tokens.verify(await service.login(client_user.email, "unit-pass")) == client_user.principal
    with pytest.raises(InvalidCredentials):
        await service.login("different@market.test", "wrong")


@pytest.mark.anyio
async def test_concurrent_failures_cannot_bypass_limit(service):
    results = await asyncio.gather(
        *(service.login("unknown@market.test", "wrong") for _ in range(15)), return_exceptions=True,
    )
    assert sum(isinstance(result, InvalidCredentials) for result in results) == 10
    assert sum(isinstance(result, LoginThrottled) for result in results) == 5
    assert not service._locks


@pytest.mark.anyio
async def test_success_resets_failure_window(service, client_user):
    for _ in range(9):
        with pytest.raises(InvalidCredentials):
            await service.login(client_user.email, "wrong")
    await service.login(client_user.email, "unit-pass")
    for _ in range(2):
        with pytest.raises(InvalidCredentials):
            await service.login(client_user.email, "wrong")


def test_window_expires_and_uses_configured_threshold():
    now = [100.0]
    limiter = FailureLimiter(2, 5, clock=lambda: now[0])
    limiter.failed("one")
    now[0] = 102
    limiter.failed("one")
    with pytest.raises(LoginThrottled) as failure:
        limiter.check("one")
    assert failure.value.retry_after == 3
    now[0] = 105
    limiter.check("one")
    now[0] = 107
    limiter.check("one")
    assert not limiter.failures


def test_failure_keys_are_bounded_and_evict_the_least_recent_failure():
    limiter = FailureLimiter(2, 300, max_keys=2)
    limiter.failed("oldest")
    limiter.failed("second")
    limiter.failed("oldest")  # Son dernier échec est maintenant le plus récent.
    limiter.failed("new")
    assert set(limiter.failures) == {"oldest", "new"}
    with pytest.raises(LoginThrottled):
        limiter.check("oldest")
    limiter.check("second")
    for index in range(20):
        limiter.failed(str(index))
        assert len(limiter.failures) <= 2
