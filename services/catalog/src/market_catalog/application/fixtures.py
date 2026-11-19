"""Fixtures du catalogue : un vendeur de démonstration, ses produits (deux catégories) et une offre par produit.

Identifiants stables (`uuid5`), donc rétablir les fixtures est idempotent et ne touche aucun autre document : les
produits du jeu de démonstration (`PRD_…`, chargés à part) ne peuvent pas entrer en collision avec elles.
Chargement réservé à `ENVIRONMENT=local` : ce sont des données de démonstration, pas des données de production.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

from market_catalog.domain.model import Offer, Product, Seller

LOCAL_ENVIRONMENT = "local"

# Identifiant du vendeur = `sub` du compte seller@market.test émis par `auth` (même formule, aucun appel réseau).
DEMO_SELLER_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "market:seller@market.test"))
DEMO_SELLER = Seller(id=DEMO_SELLER_ID, name="Boutique de démonstration")
FIXTURES_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

logger = logging.getLogger(__name__)


class FixturesRefused(RuntimeError):
    """Fixtures demandées hors de l'environnement local."""


class FixtureRepository(Protocol):
    async def has_products(self) -> bool: ...

    async def upsert_seller(self, seller: Seller, created_at: datetime) -> None: ...

    async def upsert_products(self, products: Iterable[Product]) -> None: ...

    async def upsert_offers(self, offers: Iterable[Offer]) -> None: ...


def _fixture_id(kind: str, slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"market:fixture:{kind}:{slug}"))


# (slug, titre, catégorie, attributs, prix en centimes)
_CATALOG: list[tuple[str, str, str, dict[str, Any], int]] = [
    ("headphones", "Casque sans fil", "electronics",
     {"brand": "Sonora", "model": "SX-200", "warranty_months": 24, "power_watts": 2}, 8990),
    ("keyboard", "Clavier mécanique", "electronics", {"brand": "Keyon", "model": "K87", "warranty_months": 24}, 7450),
    ("monitor", "Écran 27 pouces", "electronics",
     {"brand": "Vistal", "model": "V27Q", "warranty_months": 36, "power_watts": 35}, 25900),
    ("speaker", "Enceinte portable", "electronics", {"brand": "Sonora", "warranty_months": 12, "power_watts": 20},
     4990),
    ("charger", "Chargeur USB-C 65 W", "electronics", {"brand": "Voltix", "warranty_months": 12, "power_watts": 65},
     2990),
    ("webcam", "Webcam HD", "electronics", {"brand": "Vistal", "model": "C920", "warranty_months": 24}, 5990),
    ("miserables", "Les Misérables", "books",
     {"author": "Victor Hugo", "isbn": "9782070409189", "pages": 1664, "language": "fr"}, 1290),
    ("etranger", "L'Étranger", "books", {"author": "Albert Camus", "isbn": "9782070360024", "pages": 191,
                                         "language": "fr"}, 790),
    ("petit-prince", "Le Petit Prince", "books",
     {"author": "Antoine de Saint-Exupéry", "isbn": "9782070612758", "pages": 104, "language": "fr"}, 890),
    ("germinal", "Germinal", "books", {"author": "Émile Zola", "isbn": "9782253004226", "language": "fr"}, 650),
    ("dune", "Dune", "books", {"author": "Frank Herbert", "isbn": "9780441172719", "pages": 896, "language": "en"},
     1150),
    ("1984", "1984", "books", {"author": "George Orwell", "isbn": "9780451524935", "pages": 328, "language": "en"},
     990),
]

FIXTURE_PRODUCTS = [
    Product(id=_fixture_id("product", slug), title=title, category=category, seller_id=DEMO_SELLER_ID,
            created_at=FIXTURES_CREATED_AT, attributes=attributes)
    for slug, title, category, attributes, _ in _CATALOG
]
FIXTURE_OFFERS = [
    Offer(id=_fixture_id("offer", slug), product_id=_fixture_id("product", slug), seller_id=DEMO_SELLER_ID,
          price_cents=price, currency="EUR", created_at=FIXTURES_CREATED_AT)
    for slug, _, _, _, price in _CATALOG
]


def ensure_local(environment: str) -> None:
    if environment != LOCAL_ENVIRONMENT:
        raise FixturesRefused(f"fixtures refusées hors de l'environnement {LOCAL_ENVIRONMENT} ({environment!r})")


async def restore_fixtures(repo: FixtureRepository, *, environment: str) -> int:
    """Crée ou rétablit le vendeur, les produits et les offres de démonstration ; rend le nombre de produits."""
    ensure_local(environment)
    await repo.upsert_seller(DEMO_SELLER, FIXTURES_CREATED_AT)
    await repo.upsert_products(FIXTURE_PRODUCTS)
    await repo.upsert_offers(FIXTURE_OFFERS)
    return len(FIXTURE_PRODUCTS)


async def load_fixtures_if_empty(repo: FixtureRepository, *, environment: str) -> None:
    """Au démarrage : un catalogue vide reçoit les fixtures en local ; ailleurs, rien n'est écrit."""
    if environment != LOCAL_ENVIRONMENT:
        logger.info("fixtures non chargées : environnement %s", environment)
        return
    if await repo.has_products():
        return
    count = await restore_fixtures(repo, environment=environment)
    logger.info("catalogue vide : %d produits de démonstration chargés", count)
