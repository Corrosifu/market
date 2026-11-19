"""Cas d'usage du catalogue contre un dépôt en mémoire : droits, bornes et entrées refusés avant toute écriture."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from market_catalog.application.products import ProductDraft, create_product, list_products
from market_catalog.domain.model import (
    InvalidRequest,
    NotASeller,
    Product,
    Seller,
    UnknownCategory,
    UnknownSeller,
)

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 15, tzinfo=UTC)
SELLER = Seller(id="7f1b6a52-0000-5000-8000-000000000001", name="Boutique")
CATEGORIES = frozenset({"books", "electronics"})


class InMemoryCatalog:
    def __init__(self) -> None:
        self.products: list[Product] = []
        self.sellers = {SELLER.id: SELLER}
        self.list_calls: list[tuple[str | None, int]] = []

    async def list_products(self, *, category: str | None, first: int) -> list[Product]:
        self.list_calls.append((category, first))
        return [p for p in self.products if category is None or p.category == category][:first]

    async def insert_product(self, product: Product) -> None:
        self.products.append(product)

    async def find_seller(self, seller_id: str) -> Seller | None:
        return self.sellers.get(seller_id)

    async def sellers_by_ids(self, seller_ids: Sequence[str]) -> list[Seller | None]:
        return [self.sellers.get(i) for i in seller_ids]


def draft(**overrides: Any) -> ProductDraft:
    fields: dict[str, Any] = {"title": "Les Misérables", "category": "books",
                              "attributes": {"author": "Hugo", "isbn": "9782070409189"}} | overrides
    return ProductDraft(**fields)


async def create(repo: InMemoryCatalog, role: str | None, user_id: str | None = SELLER.id, **overrides: Any) -> Product:
    return await create_product(repo, draft(**overrides), role=role, user_id=user_id, categories=CATEGORIES,
                                now=NOW)


async def test_seller_creates_a_product_attached_to_their_seller_id() -> None:
    repo = InMemoryCatalog()

    created = await create(repo, "seller")

    assert repo.products == [created]
    assert (created.seller_id, created.category, created.created_at) == (SELLER.id, "books", NOW)


@pytest.mark.parametrize("role", [None, "", "client", "ops", "SELLER", "seller "])
async def test_creation_is_refused_outside_the_seller_role(role: str | None) -> None:
    repo = InMemoryCatalog()

    with pytest.raises(NotASeller):
        await create(repo, role)

    assert repo.products == []


@pytest.mark.parametrize("user_id", [None, "", "unknown-user"])
async def test_creation_is_refused_without_a_matching_seller(user_id: str | None) -> None:
    repo = InMemoryCatalog()

    with pytest.raises(UnknownSeller):
        await create(repo, "seller", user_id=user_id)

    assert repo.products == []


async def test_creation_in_a_category_without_schema_is_refused() -> None:
    repo = InMemoryCatalog()

    with pytest.raises(UnknownCategory):
        await create(repo, "seller", category="toys")

    assert repo.products == []


@pytest.mark.parametrize("attributes", [
    {"$where": "sleep(1000)"},
    {"author": {"$ne": None}},
    {"a.b": 1},
    {"tags": [{"$gt": ""}]},
    {"n": 2**64},
    {"n": {"a": {"b": {"c": {"d": 1}}}}},
    {"n": [[[[1]]]]},
])
async def test_unstorable_or_operator_shaped_attributes_are_refused(attributes: dict[str, Any]) -> None:
    repo = InMemoryCatalog()

    with pytest.raises(InvalidRequest):
        await create(repo, "seller", attributes=attributes)

    assert repo.products == []


@pytest.mark.parametrize("first", [0, -1, 51, 10_000, True])
async def test_page_size_outside_the_bound_is_refused(first: int) -> None:
    repo = InMemoryCatalog()

    with pytest.raises(InvalidRequest):
        await list_products(repo, category=None, first=first, max_page_size=50)

    assert repo.list_calls == []


@pytest.mark.parametrize("category", ['{"$ne": null}', "$where", "Books", "", "a" * 65])
async def test_malformed_category_filter_is_refused(category: str) -> None:
    repo = InMemoryCatalog()

    with pytest.raises(InvalidRequest):
        await list_products(repo, category=category, first=10, max_page_size=50)

    assert repo.list_calls == []


async def test_listing_forwards_a_plain_category_and_the_bounded_size() -> None:
    repo = InMemoryCatalog()

    await list_products(repo, category="books", first=50, max_page_size=50)

    assert repo.list_calls == [("books", 50)]
