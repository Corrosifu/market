"""Contrôle du rôle sur `POST /v1/catalog/products`, avant le corps et avant toute base (application non démarrée :
aucun dépôt n'existe, un accès à MongoDB ferait échouer la requête)."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from market_catalog.main import create_app
from market_catalog.settings import CatalogSettings
from pydantic import SecretStr


@pytest.fixture
def client() -> TestClient:
    settings = CatalogSettings(mongo_url=SecretStr("mongodb://unused.invalid/catalog"), environment="test")
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.mark.parametrize("headers", [{}, {"X-User-Role": "client"}, {"X-User-Role": "ops"}, {"X-User-Role": ""}])
@pytest.mark.parametrize("body", [
    {"title": "Livre", "category": "books", "attributes": {"author": "A", "isbn": "9782070409189"}},
    {"title": "", "category": {"$ne": None}, "attributes": {"$where": "1"}},
    {},
])
def test_non_seller_gets_403_before_body_validation_and_storage(
    client: TestClient, headers: dict[str, str], body: dict[str, Any]
) -> None:
    response = client.post("/v1/catalog/products", json=body, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "création de produit réservée au rôle seller"}
