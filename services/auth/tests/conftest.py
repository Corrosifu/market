from uuid import NAMESPACE_URL, uuid5

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from market_auth.adapters.passwords import ArgonPasswords
from market_auth.adapters.tokens import RsaTokens
from market_auth.domain.identity import Principal, Role, User


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def rsa_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public


@pytest.fixture
def tokens(rsa_keys):
    return RsaTokens(*rsa_keys, issuer="test-auth", audience="test-market", ttl_seconds=900)


@pytest.fixture
def passwords():
    return ArgonPasswords()


@pytest.fixture
def users():
    class MemoryUsers:
        def __init__(self):
            self.records = {}

        async def by_email(self, email):
            return self.records.get(email)

        async def upsert(self, records):
            self.records.update({user.email: user for user in records})

    return MemoryUsers()


@pytest.fixture
async def client_user(users, passwords):
    email = "client@market.test"
    user = User(
        Principal(uuid5(NAMESPACE_URL, "market:" + email), Role.CLIENT), email, await passwords.hash("unit-pass"),
    )
    await users.upsert([user])
    return user
