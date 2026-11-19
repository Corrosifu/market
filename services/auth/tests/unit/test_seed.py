from uuid import NAMESPACE_URL, uuid5

import pytest
from market_auth.application.seed import seed_demo
from market_auth.domain.identity import Role


@pytest.mark.anyio
@pytest.mark.parametrize("environment", ["production", "staging", "LOCAL"])
async def test_demo_accounts_refused_outside_local(environment, users, passwords):
    with pytest.raises(ValueError, match="uniquement"):
        await seed_demo(users, passwords, environment, dict.fromkeys(Role, "unit-pass"))
    assert not users.records


@pytest.mark.anyio
async def test_seed_is_idempotent_restores_passwords_and_uses_stable_ids(users, passwords):
    await seed_demo(users, passwords, "local", dict.fromkeys(Role, "old-pass"))
    await seed_demo(users, passwords, "local", dict.fromkeys(Role, "restored-pass"))
    assert len(users.records) == 3
    for role in Role:
        email = f"{role.value}@market.test"
        user = users.records[email]
        assert user.principal.id == uuid5(NAMESPACE_URL, "market:" + email)
        assert user.principal.role == role
        assert await passwords.verify(user.password_hash, "restored-pass")
        assert not await passwords.verify(user.password_hash, "old-pass")
