"""Cas d'usage du catalogue : lister les produits, créer un produit (vendeur seulement)."""
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from market_catalog.domain.model import (
    SELLER_ROLE,
    NotASeller,
    Product,
    Seller,
    UnknownCategory,
    UnknownSeller,
    check_attributes,
    check_category,
    check_page_size,
)
from market_catalog.settings import MAX_ATTRIBUTE_DEPTH


class CatalogRepository(Protocol):
    async def list_products(self, *, category: str | None, first: int) -> list[Product]: ...

    async def insert_product(self, product: Product) -> None: ...

    async def find_seller(self, seller_id: str) -> Seller | None: ...

    async def sellers_by_ids(self, seller_ids: Sequence[str]) -> list[Seller | None]: ...


@dataclass(frozen=True)
class ProductDraft:
    """Produit proposé par un vendeur, avant validation par le schéma de sa catégorie."""

    title: str
    category: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    description: str | None = None


async def list_products(repo: CatalogRepository, *, category: str | None, first: int,
                        max_page_size: int) -> list[Product]:
    size = check_page_size(first, max_page_size)
    return await repo.list_products(category=None if category is None else check_category(category), first=size)


async def create_product(repo: CatalogRepository, draft: ProductDraft, *, role: str | None, user_id: str | None,
                         categories: frozenset[str], now: datetime) -> Product:
    """Le rôle vient de `X-User-Role` posé par NGINX ; le vendeur est celui dont l'identifiant est le `sub` du jeton."""
    if role != SELLER_ROLE:
        raise NotASeller("création de produit réservée au rôle seller")
    seller = await repo.find_seller(user_id) if user_id else None
    if seller is None:
        raise UnknownSeller("aucun vendeur ne correspond à cet utilisateur")
    category = check_category(draft.category)
    if category not in categories:
        raise UnknownCategory(f"catégorie sans schéma : {category}")
    check_attributes(draft.attributes, MAX_ATTRIBUTE_DEPTH)
    product = Product(id=str(uuid.uuid4()), title=draft.title, category=category, seller_id=seller.id,
                      created_at=now, attributes=dict(draft.attributes), description=draft.description)
    await repo.insert_product(product)
    return product
