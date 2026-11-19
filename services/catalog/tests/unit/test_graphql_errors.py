"""Erreurs GraphQL : les erreurs d'entrée restent lisibles, les erreurs internes (base, bug) sont masquées."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from market_catalog.domain.model import Product, Seller
from market_catalog.main import create_app
from market_catalog.settings import MAX_PAGE_SIZE, CatalogSettings
from pydantic import SecretStr
from pymongo.errors import ServerSelectionTimeoutError

INTERNAL_DETAIL = "mongo-interne.example:27017 Timeout, topology description"


class BrokenCatalog:
    async def list_products(self, *, category: str | None, first: int) -> list[Product]:
        raise ServerSelectionTimeoutError(INTERNAL_DETAIL)

    async def insert_product(self, product: Product) -> None:
        raise AssertionError("non utilisé")

    async def find_seller(self, seller_id: str) -> Seller | None:
        return None

    async def sellers_by_ids(self, seller_ids: Sequence[str]) -> list[Seller | None]:
        return [None for _ in seller_ids]


@pytest.fixture
def client() -> TestClient:
    app = create_app(CatalogSettings(mongo_url=SecretStr("mongodb://unused.invalid/catalog"), environment="test"))
    app.state.catalog = BrokenCatalog()
    return TestClient(app, raise_server_exceptions=False)


def query(client: TestClient, text: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post("/v1/catalog/graphql", json={"query": text, "variables": variables or {}})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_internal_error_is_masked_for_the_client_but_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    body = query(client, "{ products(first: 3) { id } }")

    [error] = body["errors"]
    assert error["message"] == "Erreur interne."
    assert "mongo" not in str(body).lower() and "Timeout" not in str(body)
    assert body["data"] is None
    assert any(INTERNAL_DETAIL in r.getMessage() or (r.exc_info and INTERNAL_DETAIL in str(r.exc_info[1]))
               for r in caplog.records), "l'erreur réelle reste dans les journaux du service"


def test_input_errors_stay_readable(client: TestClient) -> None:
    out_of_bound = query(client, "query($n: Int!) { products(first: $n) { id } }", {"n": MAX_PAGE_SIZE + 1})
    wrong_type = query(client, "query($c: String) { products(category: $c) { id } }", {"c": {"$ne": None}})

    assert f"entre 1 et {MAX_PAGE_SIZE}" in out_of_bound["errors"][0]["message"]
    assert "String" in wrong_type["errors"][0]["message"]
