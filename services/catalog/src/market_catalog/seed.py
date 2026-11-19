"""Rétablit les fixtures du catalogue de façon idempotente : `python -m market_catalog.seed`.

Lit `ENVIRONMENT` et `MONGO_URL` ; refusé (code 2) si `ENVIRONMENT` n'est pas `local`, sans rien écrire.
"""
from __future__ import annotations

import asyncio
import logging

from market_common import configure_logging

from market_catalog.adapters.mongo import open_catalog
from market_catalog.application.fixtures import FixturesRefused, ensure_local, restore_fixtures
from market_catalog.settings import CatalogSettings

logger = logging.getLogger("market_catalog.seed")


async def _restore(settings: CatalogSettings) -> int:
    async with open_catalog(settings.mongo_url.get_secret_value()) as (catalog, _):
        return await restore_fixtures(catalog, environment=settings.environment)


def main() -> int:
    settings = CatalogSettings()  # type: ignore[call-arg]  # MONGO_URL lu de l'environnement
    configure_logging(settings.service_name, settings.log_level)
    try:
        ensure_local(settings.environment)  # avant toute connexion : rien n'est écrit hors de local
    except FixturesRefused as err:
        logger.error("%s", err)
        return 2
    count = asyncio.run(_restore(settings))
    logger.info("fixtures du catalogue rétablies : %d produits", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
