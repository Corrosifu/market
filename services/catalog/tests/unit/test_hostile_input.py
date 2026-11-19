"""Entrées hostiles sur `POST /v1/catalog/products` : refus 4xx, jamais 500, rien d'enregistré.

L'application n'est pas démarrée : un dépôt en mémoire est posé sur `app.state` à la place de MongoDB.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from market_catalog.domain.model import Product, Seller
from market_catalog.main import create_app
from market_catalog.settings import MAX_ATTRIBUTE_DEPTH, CatalogSettings
from pydantic import SecretStr

SELLER = Seller(id="seller-1", name="Boutique")
HEADERS = {"X-User-Role": "seller", "X-User-Id": SELLER.id}


class InMemoryCatalog:
    def __init__(self) -> None:
        self.products: list[Product] = []

    async def list_products(self, *, category: str | None, first: int) -> list[Product]:
        return self.products[:first]

    async def insert_product(self, product: Product) -> None:
        self.products.append(product)

    async def find_seller(self, seller_id: str) -> Seller | None:
        return SELLER if seller_id == SELLER.id else None

    async def sellers_by_ids(self, seller_ids: Sequence[str]) -> list[Seller | None]:
        return [SELLER if i == SELLER.id else None for i in seller_ids]


@pytest.fixture
def repo() -> InMemoryCatalog:
    return InMemoryCatalog()


@pytest.fixture
def client(repo: InMemoryCatalog) -> TestClient:
    app = create_app(CatalogSettings(mongo_url=SecretStr("mongodb://unused.invalid/catalog"), environment="test"))
    app.state.catalog = repo
    app.state.categories = frozenset({"books", "electronics"})
    return TestClient(app, raise_server_exceptions=False)


def book(attributes: dict[str, Any]) -> dict[str, Any]:
    return {"title": "Livre", "category": "books", "attributes": {"author": "A", "isbn": "9782070409189", **attributes}}


def nested(depth: int) -> Any:
    value: Any = 1
    for _ in range(depth):
        value = {"k": value}
    return value


def test_attributes_at_the_depth_limit_are_accepted(client: TestClient, repo: InMemoryCatalog) -> None:
    # `attributes` compte pour un niveau : sa valeur la plus imbriquée est à MAX_ATTRIBUTE_DEPTH.
    response = client.post("/v1/catalog/products", json=book({"n": nested(MAX_ATTRIBUTE_DEPTH - 1)}), headers=HEADERS)

    assert response.status_code == 201, response.text
    assert len(repo.products) == 1


@pytest.mark.parametrize("attributes", [
    {"n": nested(MAX_ATTRIBUTE_DEPTH)},
    {"n": [[[[[[[[1]]]]]]]]},
    {"n": 2**63},
    {"n": -(2**63) - 1},
    {"n": [1, {"m": 10**30}]},
    {"n": {"$gt": ""}},
])
def test_hostile_attributes_are_refused_with_422(
    client: TestClient, repo: InMemoryCatalog, attributes: dict[str, Any]
) -> None:
    response = client.post("/v1/catalog/products", json=book(attributes), headers=HEADERS)

    assert response.status_code == 422, response.text
    assert repo.products == []


def test_64_bit_integer_bounds_are_accepted(client: TestClient, repo: InMemoryCatalog) -> None:
    response = client.post("/v1/catalog/products", json=book({"n": 2**63 - 1, "m": -(2**63)}), headers=HEADERS)

    assert response.status_code == 201, response.text


def test_extremely_deep_json_body_is_refused_without_server_error(client: TestClient, repo: InMemoryCatalog) -> None:
    body = '{"title": "Livre", "category": "books", "attributes": {"n": ' + "[" * 100_000 + "]" * 100_000 + "}}"

    response = client.post("/v1/catalog/products", content=body,
                           headers={**HEADERS, "Content-Type": "application/json"})

    assert 400 <= response.status_code < 500, response.text[:200]
    assert repo.products == []
