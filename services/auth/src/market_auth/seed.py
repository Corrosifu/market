"""Commande idempotente de rétablissement des comptes locaux."""
import asyncio

from market_auth.adapters.database import PostgresUsers, create_engine
from market_auth.adapters.passwords import ArgonPasswords
from market_auth.application.seed import seed_demo
from market_auth.config import Settings
from market_auth.domain.identity import Role


async def restore_accounts(settings: Settings, users: PostgresUsers, passwords: ArgonPasswords) -> None:
    await seed_demo(users, passwords, settings.environment, {
        Role.CLIENT: settings.demo_client_password.get_secret_value(),
        Role.SELLER: settings.demo_seller_password.get_secret_value(),
        Role.OPS: settings.demo_ops_password.get_secret_value(),
    })


async def main() -> None:
    settings = Settings.model_validate({})
    engine = create_engine(settings)
    try:
        passwords = ArgonPasswords(
            settings.auth_hash_concurrency, max_waiting=settings.auth_hash_max_waiting,
            wait_timeout_seconds=settings.auth_hash_wait_timeout_seconds,
            retry_after_seconds=settings.auth_hash_retry_after_seconds,
        )
        await restore_accounts(settings, PostgresUsers(engine), passwords)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
