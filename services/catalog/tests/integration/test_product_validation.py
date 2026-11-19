"""Le validateur `$jsonSchema` de MongoDB applique le schéma de la catégorie du produit."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from market_catalog.adapters.mongo import MongoCatalog, ensure_collections
from market_catalog.adapters.schemas import load_category_schemas
from market_catalog.domain.model import InvalidRequest, Product, ProductRejected
from market_catalog.settings import SCHEMAS_DIR
from pymongo import AsyncMongoClient

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
async def catalog(mongo_url: str) -> AsyncIterator[MongoCatalog]:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(mongo_url, tz_aware=True)
    db = client.get_default_database()
    await ensure_collections(db, load_category_schemas(SCHEMAS_DIR))
    yield MongoCatalog(db)
    await client.close()


def product(category: str, attributes: dict[str, Any], **overrides: Any) -> Product:
    fields: dict[str, Any] = {"id": "p-1", "title": "Produit", "category": category, "seller_id": "s-1",
                              "created_at": NOW, "attributes": attributes} | overrides
    return Product(**fields)


async def test_valid_products_of_each_category_are_accepted(catalog: MongoCatalog) -> None:
    await catalog.insert_product(product("electronics", {"brand": "Acme", "warranty_months": 24}, id="e-1"))
    await catalog.insert_product(product("books", {"author": "Hugo", "isbn": "9782070409189"}, id="b-1"))

    stored = await catalog.list_products(category=None, first=10)

    assert [(p.id, p.category) for p in stored] == [("b-1", "books"), ("e-1", "electronics")]


@pytest.mark.parametrize(("category", "attributes"), [
    ("books", {"brand": "Acme", "warranty_months": 24}),           # attributs d'une autre catégorie
    ("electronics", {"brand": "Acme"}),                            # attribut obligatoire manquant
    ("electronics", {"brand": "Acme", "warranty_months": "24"}),   # mauvais type
    ("books", {"author": "Hugo", "isbn": "pas-un-isbn"}),          # motif non respecté
    ("books", {"author": "Hugo", "isbn": "9782070409189", "$where": "1"}),  # attribut inconnu
])
async def test_document_violating_its_category_schema_is_rejected(
    catalog: MongoCatalog, category: str, attributes: dict[str, Any]
) -> None:
    with pytest.raises(ProductRejected):
        await catalog.insert_product(product(category, attributes))

    assert await catalog.list_products(category=None, first=10) == []


async def test_category_without_schema_is_rejected_by_the_database(catalog: MongoCatalog) -> None:
    with pytest.raises(ProductRejected):
        await catalog.insert_product(product("toys", {"brand": "Acme", "warranty_months": 1}))


@pytest.mark.parametrize("attributes", [
    {"author": "Hugo", "isbn": "9782070409189", "n": 2**70},   # entier non encodable en BSON
    {"author": "Hugo", "isbn": "9782070409189", "a\x00b": 1},  # clé non encodable en BSON
])
async def test_unencodable_document_is_an_invalid_request_not_a_crash(
    catalog: MongoCatalog, attributes: dict[str, Any]
) -> None:
    with pytest.raises(InvalidRequest):
        await catalog.insert_product(product("books", attributes))

    assert await catalog.list_products(category=None, first=10) == []
