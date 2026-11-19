"""Migrations asynchrones exécutées avec le rôle auth_svc."""
import asyncio

from alembic import context
from market_auth.adapters.database import Base, create_engine
from market_auth.config import Settings
from sqlalchemy import Connection


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, version_table_schema="auth")
    with context.begin_transaction():
        context.run_migrations()


async def run() -> None:
    engine = create_engine(Settings.model_validate({}))
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


asyncio.run(run())
