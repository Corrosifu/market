import asyncio

from alembic import context
from market_inventory.config import Settings, create_engine
from sqlalchemy import Connection


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, version_table_schema="inventory")
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
