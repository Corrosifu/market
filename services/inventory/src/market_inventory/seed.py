"""Restaure les trois positions de stock des essais locaux (destructif pour leurs réservations)."""

import asyncio

from market_inventory.adapters.postgres import PostgresInventory
from market_inventory.config import Settings, create_engine


async def seed() -> None:
    settings = Settings.model_validate({})
    engine = create_engine(settings)
    try:
        await PostgresInventory(engine).seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
