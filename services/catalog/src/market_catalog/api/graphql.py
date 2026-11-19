"""GraphQL du catalogue (Strawberry), `POST /v1/catalog/graphql`.

- `products(category, first)` : mêmes bornes que le REST (`first` dans [1, MAX_PAGE_SIZE], catégorie simple).
- Le vendeur d'un produit passe par un DataLoader créé pour chaque requête : une seule lecture des vendeurs pour
  toute la page, au lieu d'une par produit (N+1).
- Coût borné : profondeur, nombre de jetons et d'alias limités ; pas de GET (ni IDE), pas d'envoi de fichiers.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import strawberry
from fastapi import Request
from graphql import GraphQLError
from market_catalog.application.products import CatalogRepository
from market_catalog.application.products import list_products as list_products_use_case
from market_catalog.domain.model import InvalidRequest, Product, Seller
from market_catalog.settings import (
    DEFAULT_PAGE_SIZE,
    GRAPHQL_MAX_ALIASES,
    GRAPHQL_MAX_DEPTH,
    GRAPHQL_MAX_TOKENS,
    MAX_PAGE_SIZE,
)
from strawberry.dataloader import DataLoader
from strawberry.extensions import MaskErrors, MaxAliasesLimiter, MaxTokensLimiter, QueryDepthLimiter
from strawberry.fastapi import BaseContext, GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info


class CatalogContext(BaseContext):
    def __init__(self, repo: CatalogRepository) -> None:
        super().__init__()
        self.repo = repo

        async def load_sellers(ids: list[str]) -> Sequence[Seller | None]:
            return await repo.sellers_by_ids(ids)

        self.seller_loader: DataLoader[str, Seller | None] = DataLoader(load_fn=load_sellers)


@strawberry.type(name="Seller")
class SellerType:
    id: strawberry.ID
    name: str


@strawberry.type(name="Product")
class ProductType:
    id: strawberry.ID
    title: str
    category: str
    description: str | None
    seller_id: strawberry.ID
    attributes: JSON

    @strawberry.field
    async def seller(self, info: Info[CatalogContext, None]) -> SellerType | None:
        seller = await info.context.seller_loader.load(str(self.seller_id))
        return None if seller is None else SellerType(id=strawberry.ID(seller.id), name=seller.name)

    @classmethod
    def of(cls, product: Product) -> ProductType:
        return cls(id=strawberry.ID(product.id), title=product.title, category=product.category,
                   description=product.description, seller_id=strawberry.ID(product.seller_id),
                   attributes=JSON(dict(product.attributes)))


@strawberry.type
class Query:
    @strawberry.field
    async def products(self, info: Info[CatalogContext, None], category: str | None = None,
                       first: int = DEFAULT_PAGE_SIZE) -> list[ProductType]:
        try:
            products = await list_products_use_case(info.context.repo, category=category, first=first,
                                                    max_page_size=MAX_PAGE_SIZE)
        except InvalidRequest as err:
            raise GraphQLError(str(err)) from err
        return [ProductType.of(p) for p in products]


def is_internal_error(error: GraphQLError) -> bool:
    """Masquée : une exception non prévue (base, bug), qui peut révéler l'infrastructure. Laissées lisibles : les
    erreurs d'entrée (syntaxe, type, limites) et les `GraphQLError` levées volontairement par les résolveurs."""
    return error.original_error is not None and not isinstance(error.original_error, GraphQLError)


# Fabriques : Strawberry construit une extension neuve à chaque requête.
schema = strawberry.Schema(query=Query, extensions=[
    lambda: QueryDepthLimiter(max_depth=GRAPHQL_MAX_DEPTH),
    lambda: MaxTokensLimiter(max_token_count=GRAPHQL_MAX_TOKENS),
    lambda: MaxAliasesLimiter(max_alias_count=GRAPHQL_MAX_ALIASES),
    lambda: MaskErrors(should_mask_error=is_internal_error, error_message="Erreur interne."),
])


async def get_context(request: Request) -> CatalogContext:
    return CatalogContext(request.app.state.catalog)


def graphql_router() -> GraphQLRouter[Any, None]:
    return GraphQLRouter(schema, prefix="/v1/catalog/graphql", graphql_ide=None, allow_queries_via_get=False,
                         context_getter=get_context, tags=["catalogue"])
