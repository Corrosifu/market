"""Les validateurs acceptent les documents du jeu de démonstration (ADR 0001) : `provenance_kind` conservé sur
chaque document, devise GBP conservée."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo.database import Database
from pymongo.errors import WriteError

NOW = datetime(2026, 11, 15, tzinfo=UTC)


@pytest.fixture
def db(mongo_db: Database[dict[str, Any]], api: TestClient) -> Database[dict[str, Any]]:
    """Base dont les collections et validateurs ont été posés par le démarrage de l'application."""
    return mongo_db


def test_seller_offer_and_products_with_provenance_kind_and_gbp_are_accepted(db: Database[dict[str, Any]]) -> None:
    db.sellers.insert_one({"_id": "SELLER_SYN_0001", "name": "Vendeur", "created_at": NOW,
                           "provenance_kind": "synthetic"})
    db.products.insert_many([
        {"_id": "PRD_000001", "title": "Livre", "category": "books", "seller_id": "SELLER_SYN_0001",
         "created_at": NOW, "attributes": {"author": "A", "isbn": "9782070409189"}, "provenance_kind": "observed"},
        {"_id": "PRD_000002", "title": "Casque", "category": "electronics", "seller_id": "SELLER_SYN_0001",
         "created_at": NOW, "attributes": {"brand": "B", "warranty_months": 12}, "provenance_kind": "synthetic"},
    ])
    db.offers.insert_many([
        {"_id": "OFFER_SYN_0001", "product_id": "PRD_000001", "seller_id": "SELLER_SYN_0001", "price_cents": 899,
         "currency": "GBP", "created_at": NOW, "provenance_kind": "synthetic"},
        {"_id": "OFFER_SYN_0002", "product_id": "PRD_000002", "seller_id": "SELLER_SYN_0001", "price_cents": 4999,
         "currency": "EUR", "created_at": NOW},
    ])

    assert db.products.count_documents({"provenance_kind": {"$exists": True}}) == 2
    assert db.offers.count_documents({}) == 2


@pytest.mark.parametrize(("collection", "document"), [
    ("offers", {"_id": "o", "product_id": "p", "seller_id": "s", "price_cents": 1, "currency": "USD",
                "created_at": NOW}),
    ("offers", {"_id": "o", "product_id": "p", "seller_id": "s", "price_cents": 1, "currency": "GBP",
                "created_at": NOW, "provenance_kind": 3}),
    ("sellers", {"_id": "s", "name": "V", "created_at": NOW, "provenance_kind": ""}),
    ("products", {"_id": "p", "title": "Livre", "category": "books", "seller_id": "s", "created_at": NOW,
                  "attributes": {"author": "A", "isbn": "9782070409189"}, "provenance_kind": None}),
])
def test_other_currencies_and_malformed_provenance_kind_are_rejected(
    db: Database[dict[str, Any]], collection: str, document: dict[str, Any]
) -> None:
    with pytest.raises(WriteError):
        db[collection].insert_one(document)
