"""État final PostgreSQL du paquet v3, sans appel aux services métier."""
import csv
import io
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.demo.dataset import CatalogData, csv_rows
from data.demo.errors import DatasetError

Row = dict[str, str | None]
BinaryRunner = Callable[..., subprocess.CompletedProcess[bytes]]
# Ordre de suppression : enfants avant parents ; seules ces constantes deviennent du SQL.
TABLES = {
    "inventory_movements": ("inventory.inventory_movements", (
        "movement_id", "sku", "product_id", "seller_id", "hub_id", "order_item_id", "movement_type",
        "quantity_delta", "occurred_at", "provenance_kind")),
    "stock_reservations": ("inventory.stock_reservations", (
        "reservation_id", "order_id", "sku", "product_id", "seller_id", "hub_id", "quantity", "status",
        "created_at", "provenance_kind")),
    "inventory": ("inventory.stock", (
        "sku", "available", "reserved", "on_hand", "product_id", "seller_id", "hub_id", "updated_at",
        "provenance_kind")),
    "order_items": ("orders.order_lines", (
        "id", "order_id", "sku", "quantity", "unit_price_gbp", "product_id", "seller_id", "provenance_kind")),
    "orders": ("orders.orders", (
        "id", "ordered_at", "customer_id", "status", "historical_status", "currency", "total_gbp", "provenance_kind")),
    "payments": ("payment.payments", (
        "payment_id", "order_id", "shipment_id", "payment_type", "method", "amount_gbp", "currency", "status",
        "created_at", "provenance_kind")),
}


@dataclass
class PostgresData:
    rows: dict[str, list[Row]]

    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.rows.items()}


def _utc(value: str) -> str:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)  # Hypothèse de l'ADR 0001 : les dates naïves du paquet sont UTC.
    return stamp.astimezone(UTC).isoformat()


def read_postgres(package: Path, catalog: CatalogData) -> PostgresData:
    """Réutiliser la sélection du catalogue, en distinguant clé absente et clé non retenue."""
    sources = {name: csv_rows(package, name) for name in TABLES}
    offers = csv_rows(package, "offers")
    pairs = {(r["product_id"], r["seller_id"]): r["offer_id"] for r in offers}
    triples = {(r["product_id"], r["seller_id"], r["hub_id"]): r["offer_id"] for r in offers}
    if len(pairs) != len(offers) or len(triples) != len(offers):
        raise DatasetError("Offres ambiguës pour les clés produit/vendeur/hub")
    all_orders = {r["order_id"] for r in sources["orders"]}
    all_items = {r["order_item_id"] for r in sources["order_items"]}
    chosen_orders = set(catalog.order_ids)
    chosen_offers = {r["_id"] for r in catalog.documents["offers"]}
    chosen_items = {r["order_item_id"] for r in sources["order_items"] if r["order_id"] in chosen_orders}
    rows: dict[str, list[Row]] = {name: [] for name in TABLES}
    try:
        for r in sources["orders"]:
            if r["order_id"] in chosen_orders:
                rows["orders"].append({
                    "id": r["order_id"], "ordered_at": _utc(r["ordered_at"]), "customer_id": r["customer_id"],
                    "status": "CONFIRMED", "historical_status": r["simulated_status"], "currency": "GBP",
                    "total_gbp": r["merchandise_total_gbp"], "provenance_kind": r["provenance_kind"]})
        for r in sources["order_items"]:
            if r["order_id"] not in all_orders:
                raise DatasetError(f"Commande absente du paquet : {r['order_id']}")
            sku = pairs[(r["product_id"], r["seller_id"])]
            if r["order_id"] in chosen_orders:
                rows["order_items"].append({
                    "id": r["order_item_id"], "order_id": r["order_id"], "sku": sku, "quantity": r["quantity"],
                    "unit_price_gbp": r["unit_price_gbp"], "product_id": r["product_id"],
                    "seller_id": r["seller_id"], "provenance_kind": r["provenance_kind"]})
        for r in sources["payments"]:
            if r["order_id"] not in all_orders:
                raise DatasetError(f"Commande absente du paquet : {r['order_id']}")
            if r["order_id"] in chosen_orders:
                rows["payments"].append({
                    "payment_id": r["payment_id"], "order_id": r["order_id"], "shipment_id": r["shipment_id"] or None,
                    "payment_type": r["payment_type"], "method": r["method"], "amount_gbp": r["amount_gbp"],
                    "currency": "GBP", "status": r["status"], "created_at": _utc(r["payment_at"]),
                    "provenance_kind": r["provenance_kind"]})
        for name in ("inventory", "stock_reservations", "inventory_movements"):
            for r in sources[name]:
                sku = triples[(r["product_id"], r["seller_id"], r["hub_id"])]
                item = r.get("order_item_id") or None
                if item is not None and item not in all_items:
                    raise DatasetError(f"Ligne absente du paquet : {item}")
                if sku not in chosen_offers:
                    continue
                common: Row = {key: r[key] for key in ("product_id", "seller_id", "hub_id", "provenance_kind")}
                common["sku"] = sku
                if name == "inventory":
                    common.update(available=r["available_quantity"], reserved=r["reserved_quantity"],
                                  on_hand=r["on_hand_quantity"], updated_at=_utc(r["snapshot_at"]))
                elif name == "stock_reservations":
                    common.update(reservation_id=r["reservation_id"], order_id=None, quantity=r["quantity"],
                                  status=r["status"], created_at=_utc(r["created_at"]))
                else:
                    common.update(movement_id=r["movement_id"], order_item_id=item if item in chosen_items else None,
                                  movement_type=r["movement_type"], quantity_delta=r["quantity_delta"],
                                  occurred_at=_utc(r["occurred_at"]))
                rows[name].append(common)
    except (KeyError, ValueError) as exc:
        raise DatasetError(f"Clé absente ou valeur invalide dans le paquet PostgreSQL : {exc}") from exc
    stock = {r["sku"] for r in rows["inventory"]}
    for name, records in rows.items():
        identity = TABLES[name][1][0]
        ids = [r[identity] for r in records]
        if len(ids) != len(set(ids)):
            raise DatasetError(f"Identifiants dupliqués : {name}")
        if any(not r["provenance_kind"] for r in records):
            raise DatasetError(f"provenance_kind absent : {name}")
        if name in {"order_items", "stock_reservations", "inventory_movements"}:
            if any(r["sku"] not in stock for r in records):
                raise DatasetError(f"Stock absent pour une référence : {name}")
    if {r["id"] for r in rows["orders"]} != chosen_orders or stock != chosen_offers:
        raise DatasetError("Commandes ou stock absents pour la sélection du catalogue")
    return PostgresData(rows)


def run_binary_command(args: list[str], *, input: bytes) -> subprocess.CompletedProcess[bytes]:
    # Aucun mode texte : conserver les LF même sous Windows, notamment pour les commandes \copy.
    return subprocess.run(args, input=input, capture_output=True, check=False, timeout=600)  # noqa: S603


def import_postgres(data: PostgresData, cache: Path, *, run: BinaryRunner = run_binary_command) -> dict[str, int]:
    """Une session, une transaction, puis comptes relus dans les six tables."""
    script = io.StringIO(newline="")
    script.write("SET TIME ZONE 'UTC';\nBEGIN;\n")
    for table, _ in TABLES.values():
        # Noms de tables constants ; aucune valeur du paquet n'entre dans le SQL.
        script.write(f"DO $$ BEGIN IF to_regclass('{table}') IS NULL THEN "  # noqa: S608
                     "RAISE EXCEPTION 'Tables absentes : lancer make up'; END IF; END $$;\n")
    for table, _ in TABLES.values():
        script.write(f"DELETE FROM {table} WHERE provenance_kind IS NOT NULL;\n")  # noqa: S608 -- Constantes.
    for name, (table, columns) in reversed(TABLES.items()):
        script.write(f"\\copy {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv)\n")
        writer = csv.writer(script, lineterminator="\n")
        writer.writerows([row[column] for column in columns] for row in data.rows[name])
        script.write("\\.\n")
    counts = ", ".join(f"'{name}', (SELECT count(*) FROM {table} WHERE provenance_kind IS NOT NULL)"  # noqa: S608
                       for name, (table, _) in TABLES.items())  # Noms exclusivement constants.
    script.write(f"SELECT json_build_object({counts});\nCOMMIT;\n")  # noqa: S608 -- SQL constant.
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "postgres.sql"
    content = script.getvalue().encode("utf-8")
    path.write_bytes(content)
    result = run(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "market",
                  "-X", "-qAt", "-v", "ON_ERROR_STOP=1"], input=content)
    if result.returncode:
        raise DatasetError("Import PostgreSQL échoué : " + result.stderr.decode("utf-8", errors="replace")[-3000:])
    try:
        actual = json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise DatasetError("Comptes PostgreSQL après import illisibles") from exc
    if actual != data.counts():
        raise DatasetError(f"Comptes PostgreSQL après import {actual}, attendus {data.counts()}")
    return actual
