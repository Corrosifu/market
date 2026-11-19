"""Accès MongoDB du catalogue (client asynchrone natif de pymongo).

Chaque filtre est construit ici, à partir de valeurs typées (`str`, `int`) : aucune structure venue d'un client
n'est transmise telle quelle à MongoDB, donc aucun opérateur (`$ne`, `$where`...) ne peut être injecté.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from bson.errors import InvalidDocument
from market_catalog.adapters.schemas import (
    OFFER_SCHEMA,
    SELLER_SCHEMA,
    CategorySchemas,
    load_category_schemas,
    products_validator,
)
from market_catalog.domain.model import InvalidRequest, Offer, Product, ProductRejected, Seller
from market_catalog.settings import DEFAULT_DATABASE, MONGO_SERVER_SELECTION_TIMEOUT_MS, SCHEMAS_DIR
from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import WriteError
from pymongo.monitoring import CommandListener

Document = dict[str, Any]

PRODUCTS, OFFERS, SELLERS = "products", "offers", "sellers"
DOCUMENT_VALIDATION_FAILURE = 121  # code d'erreur MongoDB d'un document refusé par le validateur

logger = logging.getLogger(__name__)


async def ensure_collections(db: AsyncDatabase[Document], schemas: CategorySchemas) -> None:
    """Crée les collections et (ré)applique leurs validateurs ; idempotent, rejoué à chaque démarrage."""
    validators: dict[str, Mapping[str, Any]] = {
        PRODUCTS: products_validator(schemas),
        OFFERS: {"$jsonSchema": OFFER_SCHEMA},
        SELLERS: {"$jsonSchema": SELLER_SCHEMA},
    }
    existing = set(await db.list_collection_names())
    for name, validator in validators.items():
        options: dict[str, Any] = {"validator": validator, "validationLevel": "strict", "validationAction": "error"}
        if name in existing:
            await db.command("collMod", name, **options)
        else:
            await db.create_collection(name, **options)
    await db[PRODUCTS].create_index([("category", ASCENDING), ("_id", ASCENDING)])
    await db[OFFERS].create_index([("product_id", ASCENDING)])


@asynccontextmanager
async def open_catalog(mongo_url: str, *, event_listeners: Sequence[CommandListener] = ()
                       ) -> AsyncIterator[tuple[MongoCatalog, CategorySchemas]]:
    """Connexion, collections et validateurs en place ; la base est celle de l'URL, sinon `DEFAULT_DATABASE`."""
    client: AsyncMongoClient[Document] = AsyncMongoClient(
        mongo_url, tz_aware=True, appname="market-catalog",
        serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS, event_listeners=list(event_listeners),
    )
    try:
        db = client.get_default_database(default=DEFAULT_DATABASE)
        schemas = load_category_schemas(SCHEMAS_DIR)
        await ensure_collections(db, schemas)
        logger.info("catalogue prêt : base %s, catégories %s", db.name, ", ".join(sorted(schemas)))
        yield MongoCatalog(db), schemas
    finally:
        await client.close()


def _product(doc: Mapping[str, Any]) -> Product:
    return Product(id=doc["_id"], title=doc["title"], category=doc["category"], seller_id=doc["seller_id"],
                   created_at=doc["created_at"], attributes=doc.get("attributes", {}),
                   description=doc.get("description"))


def _product_doc(product: Product) -> Document:
    doc: Document = {"_id": product.id, "title": product.title, "category": product.category,
                     "seller_id": product.seller_id, "attributes": dict(product.attributes),
                     "created_at": product.created_at}
    if product.description is not None:
        doc["description"] = product.description
    return doc


class MongoCatalog:
    """Dépôt du catalogue : produits, vendeurs, offres."""

    def __init__(self, db: AsyncDatabase[Document]) -> None:
        self._db = db

    async def ping(self) -> bool:
        reply = await self._db.command("ping")
        return bool(reply.get("ok"))

    async def list_products(self, *, category: str | None, first: int) -> list[Product]:
        query: Document = {} if category is None else {"category": str(category)}
        cursor = self._db[PRODUCTS].find(query).sort("_id", ASCENDING).limit(int(first))
        return [_product(doc) async for doc in cursor]

    async def has_products(self) -> bool:
        return await self._db[PRODUCTS].find_one({}, projection={"_id": 1}) is not None

    async def insert_product(self, product: Product) -> None:
        try:
            await self._db[PRODUCTS].insert_one(_product_doc(product))
        except (OverflowError, InvalidDocument) as err:
            # Filet : la validation d'entrée refuse déjà ces cas ; un document non encodable en BSON reste une
            # erreur de la requête (422), jamais une erreur du serveur (500).
            raise InvalidRequest("document non encodable") from err
        except WriteError as err:
            if err.code == DOCUMENT_VALIDATION_FAILURE:
                logger.info("produit refusé par le schéma de la catégorie %s", product.category)
                raise ProductRejected(f"le produit ne respecte pas le schéma de la catégorie {product.category}") \
                    from err
            raise

    async def find_seller(self, seller_id: str) -> Seller | None:
        doc = await self._db[SELLERS].find_one({"_id": str(seller_id)})
        return None if doc is None else Seller(id=doc["_id"], name=doc["name"])

    async def sellers_by_ids(self, seller_ids: Sequence[str]) -> list[Seller | None]:
        """Une seule requête pour tous les identifiants (DataLoader), résultats dans l'ordre demandé."""
        ids = [str(i) for i in seller_ids]
        found = {doc["_id"]: Seller(id=doc["_id"], name=doc["name"])
                 async for doc in self._db[SELLERS].find({"_id": {"$in": ids}})}
        return [found.get(i) for i in ids]

    async def upsert_seller(self, seller: Seller, created_at: datetime) -> None:
        await self._db[SELLERS].replace_one(
            {"_id": seller.id}, {"_id": seller.id, "name": seller.name, "created_at": created_at}, upsert=True)

    async def upsert_products(self, products: Iterable[Product]) -> None:
        for product in products:
            await self._db[PRODUCTS].replace_one({"_id": product.id}, _product_doc(product), upsert=True)

    async def upsert_offers(self, offers: Iterable[Offer]) -> None:
        for offer in offers:
            await self._db[OFFERS].replace_one({"_id": offer.id}, {
                "_id": offer.id, "product_id": offer.product_id, "seller_id": offer.seller_id,
                "price_cents": offer.price_cents, "currency": offer.currency, "created_at": offer.created_at,
            }, upsert=True)
