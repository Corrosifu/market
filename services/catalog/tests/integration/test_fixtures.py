"""Données de départ du catalogue : chargées au démarrage sur une base vide, rétablies par `market_catalog.seed`."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from market_catalog import seed
from pymongo.database import Database

DEMO_SELLER_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "market:seller@market.test"))


def snapshot(db: Database[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {name: list(db[name].find({}).sort("_id")) for name in ("products", "offers", "sellers")}


def test_empty_catalog_is_filled_at_startup_in_local(app_factory: Any, mongo_db: Database[dict[str, Any]]) -> None:
    with app_factory(environment="local") as api:
        listed = api.get("/v1/catalog/products", params={"first": 50}).json()["items"]

    products = list(mongo_db.products.find({}))
    assert len(products) >= 10
    assert {p["category"] for p in products} == {"electronics", "books"}
    assert {p["seller_id"] for p in products} == {DEMO_SELLER_ID}
    assert mongo_db.sellers.find_one({"_id": DEMO_SELLER_ID}) is not None
    assert {o["product_id"] for o in mongo_db.offers.find({})} == {p["_id"] for p in products}
    assert len(listed) == len(products)


def test_startup_does_not_touch_a_catalog_that_already_has_products(
    app_factory: Any, mongo_db: Database[dict[str, Any]]
) -> None:
    with app_factory(environment="local"):
        pass
    mongo_db.products.delete_many({"_id": {"$ne": mongo_db.products.find_one({})["_id"]}})
    before = snapshot(mongo_db)

    with app_factory(environment="local"):
        pass

    assert snapshot(mongo_db) == before


@pytest.mark.parametrize("environment", ["test", "ci", "production"])
def test_startup_outside_local_loads_no_fixtures(
    app_factory: Any, mongo_db: Database[dict[str, Any]], environment: str
) -> None:
    with app_factory(environment=environment):
        pass

    assert mongo_db.products.count_documents({}) == 0
    assert mongo_db.sellers.count_documents({}) == 0


def test_seed_restores_fixtures_idempotently_without_touching_other_products(
    monkeypatch: pytest.MonkeyPatch, mongo_url: str, mongo_db: Database[dict[str, Any]]
) -> None:
    monkeypatch.setenv("MONGO_URL", mongo_url)
    monkeypatch.setenv("ENVIRONMENT", "local")
    assert seed.main() == 0
    reference = snapshot(mongo_db)
    fixture_id = reference["products"][0]["_id"]
    mongo_db.products.update_one({"_id": fixture_id}, {"$set": {"title": "Titre modifié"}})
    mongo_db.offers.delete_many({"product_id": fixture_id})
    mongo_db.products.insert_one({"_id": "PRD_000001", "title": "Produit du jeu de démonstration",
                                  "category": "books", "seller_id": "SELLER_SYN_0001",
                                  "created_at": datetime(2026, 1, 2, tzinfo=UTC),
                                  "attributes": {"author": "A", "isbn": "9782070409189"}})

    assert seed.main() == 0
    assert seed.main() == 0

    after = snapshot(mongo_db)
    assert [p for p in after["products"] if p["_id"] != "PRD_000001"] == reference["products"]
    assert after["offers"] == reference["offers"] and after["sellers"] == reference["sellers"]
    assert mongo_db.products.find_one({"_id": "PRD_000001"}) is not None


@pytest.mark.parametrize("environment", ["ci", "production", "LOCAL", ""])
def test_seed_is_refused_outside_local(
    monkeypatch: pytest.MonkeyPatch, mongo_url: str, mongo_db: Database[dict[str, Any]], environment: str
) -> None:
    monkeypatch.setenv("MONGO_URL", mongo_url)
    monkeypatch.setenv("ENVIRONMENT", environment)

    assert seed.main() != 0

    assert mongo_db.products.count_documents({}) == 0
