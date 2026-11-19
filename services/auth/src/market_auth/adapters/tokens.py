"""Signature et vérification exclusivement RS256 avec une clé locale connue."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from market_auth.domain.identity import InvalidToken, Principal, Role


class RsaTokens:
    def __init__(self, private_pem: bytes, public_pem: bytes, issuer: str, audience: str, ttl_seconds: int) -> None:
        private = serialization.load_pem_private_key(private_pem, password=None)
        public = serialization.load_pem_public_key(public_pem)
        if not isinstance(private, rsa.RSAPrivateKey) or not isinstance(public, rsa.RSAPublicKey):
            raise ValueError("Des clés RSA sont requises")
        if private.key_size < 2048 or private.public_key().public_numbers() != public.public_numbers():
            raise ValueError("Paire RSA invalide")
        self._private = private
        self._public = public
        self.issuer = issuer
        self.audience = audience
        self.ttl_seconds = ttl_seconds
        der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.kid = hashlib.sha256(der).hexdigest()

    @classmethod
    def from_files(
        cls, private_path: Path, public_path: Path, issuer: str, audience: str, ttl_seconds: int,
    ) -> "RsaTokens":
        return cls(private_path.read_bytes(), public_path.read_bytes(), issuer, audience, ttl_seconds)

    def issue(self, principal: Principal) -> str:
        return jwt.encode(
            {"sub": str(principal.id), "role": principal.role.value,
             "exp": datetime.now(UTC) + timedelta(seconds=self.ttl_seconds), "iss": self.issuer, "aud": self.audience},
            self._private, algorithm="RS256", headers={"kid": self.kid},
        )

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or header.get("kid") != self.kid:
                raise InvalidToken
            # Aucun accès réseau et aucune clé fournie par les en-têtes du jeton.
            claims = jwt.decode(
                token, self._public, algorithms=["RS256"], issuer=self.issuer, audience=self.audience,
                options={"require": ["exp", "iss", "aud", "sub", "role"]},
            )
            return Principal(UUID(claims["sub"]), Role(claims["role"]))
        except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
            raise InvalidToken from exc

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._public))
        key.update(kid=self.kid, use="sig", alg="RS256")
        return {"keys": [key]}
