"""Routes REST du catalogue, sous `/v1/catalog`.

`X-User-Role` et `X-User-Id` sont posés par NGINX après `auth_request` (valeurs du client écrasées) ; le service
leur fait confiance uniquement parce qu'aucun de ses ports n'est publié hors du réseau compose.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, status
from market_catalog.application.products import CatalogRepository, ProductDraft, create_product, list_products
from market_catalog.domain.model import (
    CATEGORY_PATTERN,
    SELLER_ROLE,
    InvalidRequest,
    NotASeller,
    Product,
    check_attributes,
)
from market_catalog.settings import DEFAULT_PAGE_SIZE, MAX_ATTRIBUTE_DEPTH, MAX_PAGE_SIZE
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class ProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    category: str = Field(pattern=CATEGORY_PATTERN)
    description: str | None = Field(default=None, max_length=2000)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def attributes_are_storable(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        try:
            check_attributes(value, MAX_ATTRIBUTE_DEPTH)
        except InvalidRequest as err:
            raise ValueError(str(err)) from err
        return value


class ProductOut(BaseModel):
    id: str
    title: str
    category: str
    seller_id: str
    description: str | None
    attributes: dict[str, Any]

    @classmethod
    def of(cls, product: Product) -> ProductOut:
        return cls(id=product.id, title=product.title, category=product.category, seller_id=product.seller_id,
                   description=product.description, attributes=dict(product.attributes))


class ProductPage(BaseModel):
    items: list[ProductOut]


class ErrorOut(BaseModel):
    """Refus métier : `{"detail": "<message>"}`."""

    detail: str


def get_repository(request: Request) -> CatalogRepository:
    repo: CatalogRepository = request.app.state.catalog
    return repo


def get_categories(request: Request) -> frozenset[str]:
    categories: frozenset[str] = request.app.state.categories
    return categories


def require_seller(x_user_role: Annotated[str | None, Header()] = None) -> None:
    """Résolue avant la validation du corps : un non-vendeur reçoit 403, sans retour sur le contenu envoyé.
    Le cas d'usage refait le contrôle (défense en profondeur)."""
    if x_user_role != SELLER_ROLE:
        raise NotASeller("création de produit réservée au rôle seller")


Repository = Annotated[CatalogRepository, Depends(get_repository)]

router = APIRouter(prefix="/v1/catalog", tags=["catalogue"])


@router.get("/products")
async def get_products(
    repo: Repository,
    category: Annotated[str | None, Query(pattern=CATEGORY_PATTERN)] = None,
    first: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ProductPage:
    products = await list_products(repo, category=category, first=first, max_page_size=MAX_PAGE_SIZE)
    return ProductPage(items=[ProductOut.of(p) for p in products])


CREATION_REFUSALS: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorOut, "description": "Rôle autre que `seller`, ou aucun vendeur pour `X-User-Id`."},
    422: {
        "description": "Corps invalide (validation de la requête), catégorie sans schéma ou produit refusé par le "
                       "schéma de sa catégorie (erreur métier, `detail` textuel).",
        "content": {"application/json": {"schema": {"anyOf": [
            {"$ref": "#/components/schemas/ErrorOut"},
            {"$ref": "#/components/schemas/HTTPValidationError"},
        ]}}},
    },
}


@router.post("/products", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_seller)],
             responses=CREATION_REFUSALS)
async def post_product(
    body: ProductIn,
    repo: Repository,
    categories: Annotated[frozenset[str], Depends(get_categories)],
    x_user_role: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
) -> ProductOut:
    draft = ProductDraft(title=body.title, category=body.category, attributes=body.attributes,
                         description=body.description)
    product = await create_product(repo, draft, role=x_user_role, user_id=x_user_id, categories=categories,
                                   now=datetime.now(UTC))
    return ProductOut.of(product)
