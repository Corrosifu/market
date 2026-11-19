import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from market_auth.domain.identity import InvalidToken, Principal, Role


def claims():
    return {"sub": str(uuid4()), "role": "client", "exp": int(time.time()) + 900,
            "iss": "test-auth", "aud": "test-market"}


def test_issue_roundtrip_and_lifetime(tokens):
    principal = Principal(uuid4(), Role.SELLER)
    token = tokens.issue(principal)
    assert tokens.verify(token) == principal
    header = jwt.get_unverified_header(token)
    assert header == {"alg": "RS256", "kid": tokens.kid, "typ": "JWT"}
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert 898 <= decoded["exp"] - time.time() <= 900


def test_rejects_alg_none(tokens):
    forged = jwt.encode(claims(), key=None, algorithm="none", headers={"kid": tokens.kid})
    with pytest.raises(InvalidToken):
        tokens.verify(forged)


def test_rejects_hs256_signed_with_public_key(tokens, rsa_keys):
    # Construction manuelle : certaines bibliothèques refusent de créer cette confusion.
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")

    message = encode({"alg": "HS256", "kid": tokens.kid}) + b"." + encode(claims())
    signature = base64.urlsafe_b64encode(hmac.new(rsa_keys[1], message, hashlib.sha256).digest()).rstrip(b"=")
    with pytest.raises(InvalidToken):
        tokens.verify((message + b"." + signature).decode())


@pytest.mark.parametrize("change", [
    {"aud": "other"}, {"iss": "other"}, {"exp": int(time.time()) - 60},
    {"sub": "not-a-uuid"}, {"role": "admin"},
])
def test_rejects_invalid_claims(tokens, rsa_keys, change):
    forged = jwt.encode(claims() | change, rsa_keys[0], algorithm="RS256", headers={"kid": tokens.kid})
    with pytest.raises(InvalidToken):
        tokens.verify(forged)


@pytest.mark.parametrize("field", ["exp", "iss", "aud", "sub", "role"])
def test_rejects_missing_required_claim(tokens, rsa_keys, field):
    payload = claims()
    payload.pop(field)
    forged = jwt.encode(payload, rsa_keys[0], algorithm="RS256", headers={"kid": tokens.kid})
    with pytest.raises(InvalidToken):
        tokens.verify(forged)


@pytest.mark.parametrize("headers", [{}, {"kid": "unknown"}])
def test_rejects_missing_or_unknown_kid(tokens, rsa_keys, headers):
    forged = jwt.encode(claims(), rsa_keys[0], algorithm="RS256", headers=headers)
    with pytest.raises(InvalidToken):
        tokens.verify(forged)


def test_ignores_remote_and_embedded_keys(tokens, rsa_keys):
    forged = jwt.encode(claims(), rsa_keys[0], algorithm="RS256", headers={
        "kid": tokens.kid, "jku": "http://untrusted.invalid/jwks", "x5u": "http://untrusted.invalid/cert",
        "jwk": {"kty": "oct", "k": "ignored"},
    })
    assert tokens.verify(forged).role == Role.CLIENT


def test_jwks_has_only_public_material_and_verifies_signature(tokens):
    key = tokens.jwks()["keys"][0]
    assert set(key) == {"kty", "n", "e", "kid", "use", "alg", "key_ops"}
    assert key["kid"] == tokens.kid and key["use"] == "sig"
    public = jwt.PyJWK.from_dict(key).key
    token = tokens.issue(Principal(uuid4(), Role.OPS))
    assert jwt.decode(token, public, algorithms=["RS256"], audience="test-market", issuer="test-auth")["role"] == "ops"


def test_rejects_mismatched_rsa_pair(rsa_keys):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from market_auth.adapters.tokens import RsaTokens

    different_public = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(ValueError, match="Paire RSA"):
        RsaTokens(rsa_keys[0], different_public, "test", "test", 900)
