"""Rétablissement transactionnel des comptes locaux de démonstration."""
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

from market_auth.application.login import Passwords, Users
from market_auth.domain.identity import Principal, Role, User


async def seed_demo(users: Users, passwords: Passwords, environment: str, demo_passwords: Mapping[Role, str]) -> None:
    if environment != "local":
        raise ValueError("Les comptes de démonstration sont autorisés uniquement en environnement local")
    records = []
    for role in Role:
        email = f"{role.value}@market.test"
        principal = Principal(uuid5(NAMESPACE_URL, "market:" + email), role)
        records.append(User(principal, email, await passwords.hash(demo_passwords[role])))
    await users.upsert(records)
