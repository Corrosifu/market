"""Identités et erreurs d'authentification, indépendantes des transports."""
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    CLIENT = "client"
    SELLER = "seller"
    OPS = "ops"


@dataclass(frozen=True)
class Principal:
    id: UUID
    role: Role


@dataclass(frozen=True)
class User:
    principal: Principal
    email: str
    password_hash: str


def normalize_email(email: str) -> str:
    return "".join(email.split()).lower()


class InvalidCredentials(Exception):
    pass


class InvalidToken(Exception):
    pass


class HashSaturated(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("Capacité de hachage temporairement indisponible")


class LoginThrottled(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("Trop de tentatives")
