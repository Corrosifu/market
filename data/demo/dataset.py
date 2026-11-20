"""Sélection déterministe et correspondance explicite vers les collections du catalogue."""
import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from data.demo.errors import DatasetError

CREATED_AT = "2026-05-01T00:00:00Z"
CI_ORDERS = 300
PREFIXES = {"sellers": "SELLER_SYN_", "products": "PRD_", "offers": "OFFER_SYN_"}
Document = dict[str, Any]


@dataclass
class CatalogData:
    documents: dict[str, list[Document]]
    order_ids: tuple[str, ...]
    order_items: int

    def counts(self) -> dict[str, int]:
        return {"orders": len(self.order_ids), "order_items": self.order_items,
                **{name: len(rows) for name, rows in self.documents.items()}}


def csv_rows(root: Path, name: str) -> list[dict[str, str]]:
    with (root / "tables" / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def seller_document(row: Mapping[str, str]) -> Document:
    return {"_id": row["seller_id"], "name": row["name"], "provenance_kind": row["provenance_kind"],
            "created_at": {"$date": CREATED_AT}}


def product_document(row: Document) -> Document:
    if not row["seller_ids"]:
        raise DatasetError(f"Produit sans vendeur : {row['_id']}")
    attributes = dict(row["attributes"])
    if row["category_id"] == "electronics":
        attributes["brand"] = row["synthetic_brand"]
    return {"_id": row["_id"], "title": row["name"], "category": row["category_id"],
            "seller_id": row["seller_ids"][0], "attributes": attributes,
            "provenance_kind": row["provenance_kind"], "created_at": {"$date": CREATED_AT}}


def offer_document(row: Mapping[str, str], product: Document) -> Document:
    price = Decimal(product["reference_price_gbp"])
    if not price.is_finite() or price < 0:
        raise DatasetError(f"Prix invalide : {product['_id']}")
    cents = int((price * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"_id": row["offer_id"], "product_id": row["product_id"], "seller_id": row["seller_id"],
            "price_cents": cents, "currency": "GBP", "provenance_kind": row["provenance_kind"],
            "created_at": {"$date": CREATED_AT}}


def read_catalog(root: Path, profile: str, *, ci_orders: int = CI_ORDERS) -> CatalogData:
    if profile not in {"ci", "demo"} or ci_orders < 1:
        raise DatasetError("Profil attendu : ci ou demo, nombre de commandes positif")
    orders = csv_rows(root, "orders")
    order_ids = sorted(row["order_id"] for row in orders)
    if len(order_ids) != len(set(order_ids)):
        raise DatasetError("Identifiants de commandes dupliqués")
    selected_orders = tuple(order_ids[:ci_orders] if profile == "ci" else order_ids)
    selected_set = set(selected_orders)
    items = [row for row in csv_rows(root, "order_items") if row["order_id"] in selected_set]
    if {row["order_id"] for row in items} != selected_set:
        raise DatasetError("Une commande retenue n'a aucune ligne")
    with (root / "products.jsonl").open(encoding="utf-8") as stream:
        all_products = [json.loads(line) for line in stream if line.strip()]
    wanted = {row["product_id"] for row in items} if profile == "ci" else {p["_id"] for p in all_products}
    products = {p["_id"]: p for p in all_products if p["_id"] in wanted}
    if set(products) != wanted:
        raise DatasetError("Une ligne de commande référence un produit absent")
    offers = [row for row in csv_rows(root, "offers") if row["product_id"] in wanted]
    if {row["product_id"] for row in offers} != wanted:
        raise DatasetError("Un produit retenu n'a aucune offre")
    required_sellers = {row["seller_id"] for row in offers} | {p["seller_ids"][0] for p in products.values()}
    sellers = csv_rows(root, "sellers")
    if profile == "ci":
        sellers = [row for row in sellers if row["seller_id"] in required_sellers]
    if not required_sellers <= {row["seller_id"] for row in sellers}:
        raise DatasetError("Une offre ou un produit référence un vendeur absent")
    documents = {
        "sellers": [seller_document(row) for row in sellers],
        "products": [product_document(product) for product in products.values()],
        "offers": [offer_document(row, products[row["product_id"]]) for row in offers],
    }
    for name, rows in documents.items():
        ids = [row["_id"] for row in rows]
        if len(set(ids)) != len(ids) or any(not identity.startswith(PREFIXES[name]) for identity in ids):
            raise DatasetError(f"Identifiants dupliqués ou hors du préfixe de démonstration : {name}")
        rows.sort(key=lambda row: row["_id"])
    return CatalogData(documents, selected_orders, len(items))
