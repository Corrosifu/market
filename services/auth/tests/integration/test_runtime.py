"""Contrôles additionnels sur la pile locale démarrée, sans exporter ses secrets."""
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[4]


def run_in_auth(code):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "auth", "python", "-"],  # noqa: S607 -- Outil de la pile de test.
        input=code, cwd=ROOT, text=True, capture_output=True, check=False, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


def test_runtime_drops_root_and_keeps_the_key_copy_private_on_tmpfs():
    run_in_auth('''
import os
import stat
from pathlib import Path

status = Path('/proc/1/status').read_text(encoding='utf-8')
uid_line = next(line for line in status.splitlines() if line.startswith('Uid:'))
assert set(uid_line.split()[1:]) == {'10001'}
key = os.stat('/run/keys/jwt_private.pem')
assert key.st_uid == 10001 and stat.S_IMODE(key.st_mode) == 0o600
assert stat.S_IMODE(os.stat('/run/keys').st_mode) == 0o700
assert any(line.split()[1:3] == ['/run/keys', 'tmpfs']
           for line in Path('/proc/mounts').read_text(encoding='utf-8').splitlines())
assert not Path('/app/.env').exists()
assert not Path('/app/infra/secrets').exists()
''')


def test_database_seed_restores_passwords_and_preserves_ids():
    run_in_auth('''
import asyncio
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import text
from market_auth.adapters.database import PostgresUsers, create_engine
from market_auth.adapters.passwords import ArgonPasswords
from market_auth.config import Settings
from market_auth.domain.identity import User
from market_auth.seed import restore_accounts

async def check():
    settings = Settings.model_validate({})
    engine = create_engine(settings)
    users, passwords = PostgresUsers(engine), ArgonPasswords()
    try:
        user = await users.by_email('client@market.test')
        assert user is not None
        await users.upsert([User(user.principal, user.email, await passwords.hash('temporary-test-password'))])
        await restore_accounts(settings, users, passwords)
        await restore_accounts(settings, users, passwords)
        for role in ('client', 'seller', 'ops'):
            email = role + '@market.test'
            restored = await users.by_email(email)
            assert restored.principal.id == uuid5(NAMESPACE_URL, 'market:' + email)
            assert restored.principal.role.value == role
            password = getattr(settings, 'demo_' + role + '_password').get_secret_value()
            assert await passwords.verify(restored.password_hash, password)
        async with engine.connect() as connection:
            assert (await connection.scalar(text('SELECT count(*) FROM auth.users'))) == 3
    finally:
        await restore_accounts(settings, users, passwords)
        await engine.dispose()

asyncio.run(check())
''')


def test_gateway_email_throttle_leaves_other_accounts_available():
    run_in_auth('''
import json
import urllib.error
import urllib.request
from uuid import uuid4
from market_auth.config import Settings

settings = Settings.model_validate({})
email = str(uuid4()) + '@market.test'

def post(email, password):
    request = urllib.request.Request('http://gateway/v1/auth/login',
        data=json.dumps({'email': email, 'password': password}).encode(),
        headers={'Content-Type': 'application/json', 'X-User-Role': 'ops'}, method='POST')
    try:
        return urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as response:
        return response

for _ in range(settings.auth_max_failures):
    with post(email, 'wrong') as response:
        assert response.status == 401
with post(email, 'wrong') as response:
    assert response.status == 429 and int(response.headers['Retry-After']) > 0
for role in ('client', 'seller', 'ops'):
    password = getattr(settings, 'demo_' + role + '_password').get_secret_value()
    with post(role + '@market.test', password) as response:
        assert response.status == 200
''')
