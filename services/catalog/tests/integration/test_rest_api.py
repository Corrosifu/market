"""API REST du catalogue contre MongoDB : lecture bornée, création réservée au vendeur, entrées hostiles sans effet."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from market_catalog.settings import MAX_PAGE_SIZE
from pymongo.database import Database

SELLER_ID = "0b8a3c1e-8f5e-5a7e-9a4e-3f6c2d1b0a99"
NOW = datetime(2026, 11, 15, tzinfo=UTC)
BOOK = {"title": "Les Misérables", "category": "books", "attributes": {"author": "Hugo", "isbn": "9782070409189"}}
SELLER_HEADERS = {"X-User-Role": "seller", "X-User-Id": SELLER_ID}


@pytest.fixture
def db(mongo_db: Database[dict[str, Any]], api: TestClient) -> Database[dict[str, Any]]:
    """Base préparée après le démarrage de l'application (collections et validateurs en place)."""
    mongo_db.sellers.insert_one({"_id": SELLER_ID, "name": "Boutique", "created_at": NOW})
    mongo_db.products.insert_many([
        {"_id": f"p-{i:02d}", "title": f"Produit {i}", "category": "books" if i % 2 else "electronics",
         "seller_id": SELLER_ID, "created_at": NOW,
         "attributes": {"author": "A", "isbn": "9782070409189"} if i % 2 else {"brand": "B", "warranty_months": 12}}
        for i in range(MAX_PAGE_SIZE + 5)
    ])
    return mongo_db


def test_products_are_listed_and_filtered_by_category(api: TestClient, db: Database[dict[str, Any]]) -> None:
    response = api.get("/v1/catalog/products", params={"category": "books", "first": 3})

    assert response.status_code == 200
    items = response.json()["items"]
    assert [p["id"] for p in items] == ["p-01", "p-03", "p-05"]
    assert {(p["category"], p["seller_id"]) for p in items} == {("books", SELLER_ID)}
    assert items[0]["title"] == "Produit 1"


@pytest.mark.parametrize("first", [0, -1, MAX_PAGE_SIZE + 1, 1_000_000])
def test_first_outside_the_bound_is_refused(api: TestClient, db: Database[dict[str, Any]], first: int) -> None:
    response = api.get("/v1/catalog/products", params={"first": first})

    assert response.status_code == 422


def test_first_at_the_bound_returns_at_most_the_bound(api: TestClient, db: Database[dict[str, Any]]) -> None:
    response = api.get("/v1/catalog/products", params={"first": MAX_PAGE_SIZE})

    assert response.status_code == 200
    assert len(response.json()["items"]) == MAX_PAGE_SIZE


@pytest.mark.parametrize("category", ['{"$ne": null}', "$where", "books' || '1'=='1"])
def test_operator_shaped_category_filter_has_no_effect(
    api: TestClient, db: Database[dict[str, Any]], category: str
) -> None:
    response = api.get("/v1/catalog/products", params={"category": category})

    assert response.status_code == 422
    assert "items" not in response.json()


def test_seller_creates_a_product_that_is_then_listed(api: TestClient, db: Database[dict[str, Any]]) -> None:
    response = api.post("/v1/catalog/products", json=BOOK, headers=SELLER_HEADERS)

    assert response.status_code == 201, response.text
    created = response.json()
    assert (created["title"], created["category"], created["seller_id"]) == (BOOK["title"], "books", SELLER_ID)
    stored = db.products.find_one({"_id": created["id"]})
    assert stored is not None and stored["attributes"] == BOOK["attributes"]


@pytest.mark.parametrize("headers", [
    {},
    {"X-User-Role": "client", "X-User-Id": SELLER_ID},
    {"X-User-Role": "ops", "X-User-Id": SELLER_ID},
    {"X-User-Role": "", "X-User-Id": SELLER_ID},
])
def test_creation_is_refused_outside_the_seller_role(
    api: TestClient, db: Database[dict[str, Any]], headers: dict[str, str]
) -> None:
    before = db.products.count_documents({})

    response = api.post("/v1/catalog/products", json=BOOK, headers=headers)

    assert response.status_code == 403
    assert db.products.count_documents({}) == before


@pytest.mark.parametrize("body", [
    {"title": "", "category": "toys", "attributes": {"$where": "1"}},
    {"category": {"$ne": None}},
    {},
])
def test_role_is_checked_before_the_body_is_validated(
    api: TestClient, db: Database[dict[str, Any]], body: dict[str, Any]
) -> None:
    before = db.products.count_documents({})

    response = api.post("/v1/catalog/products", json=body, headers={"X-User-Role": "client", "X-User-Id": SELLER_ID})

    assert response.status_code == 403, response.text
    assert db.products.count_documents({}) == before


def test_seller_without_seller_record_is_refused(api: TestClient, db: Database[dict[str, Any]]) -> None:
    response = api.post("/v1/catalog/products", json=BOOK, headers={"X-User-Role": "seller", "X-User-Id": "nobody"})

    assert response.status_code == 403


@pytest.mark.parametrize("body", [
    {**BOOK, "attributes": {"brand": "Acme", "warranty_months": 12}},       # attributs d'une autre catégorie
    {**BOOK, "attributes": {"author": "Hugo", "isbn": "123"}},              # isbn invalide
    {**BOOK, "category": "toys"},                                            # catégorie sans schéma
    {**BOOK, "category": {"$ne": None}},                                     # opérateur à la place d'une chaîne
    {**BOOK, "attributes": {"author": {"$gt": ""}, "isbn": "9782070409189"}},
    {**BOOK, "seller_id": "someone-else"},                                   # champ non prévu
    {**BOOK, "title": ""},
])
def test_invalid_product_is_refused_and_not_stored(
    api: TestClient, db: Database[dict[str, Any]], body: dict[str, Any]
) -> None:
    before = db.products.count_documents({})

    response = api.post("/v1/catalog/products", json=body, headers=SELLER_HEADERS)

    assert response.status_code == 422, response.text
    assert db.products.count_documents({}) == before
