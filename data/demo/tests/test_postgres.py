import csv
import subprocess
from datetime import datetime, timedelta

import pytest

from data.demo.dataset import read_catalog
from data.demo.errors import DatasetError
from data.demo.postgres import import_postgres, read_postgres


def test_postgres_mapping_reuses_catalog_selection_and_keeps_values_and_utc(packet):
    catalog = read_catalog(packet, "ci", ci_orders=2)
    data = read_postgres(packet, catalog)
    assert data.counts() == {"orders": 2, "order_items": 2, "payments": 2, "inventory": 2,
                             "stock_reservations": 2, "inventory_movements": 3}
    order = data.rows["orders"][0]
    assert (order["id"], order["status"], order["historical_status"], order["total_gbp"], order["currency"]) == (
        "order-a", "CONFIRMED", "DELIVERED", "19.50", "GBP")
    line = data.rows["order_items"][0]
    assert (line["id"], line["quantity"], line["unit_price_gbp"], line["sku"]) == (
        "line-a", "6", "3.25", "OFFER_SYN_a")
    payment = data.rows["payments"][0]
    assert (payment["status"], payment["amount_gbp"], payment["currency"]) == ("SUCCEEDED", "19.50", "GBP")
    stock = data.rows["inventory"][0]
    assert (stock["available"], stock["reserved"], stock["on_hand"]) == ("8", "2", "10")
    stamps = (order["ordered_at"], payment["created_at"], stock["updated_at"],
              data.rows["stock_reservations"][0]["created_at"], data.rows["inventory_movements"][0]["occurred_at"])
    assert all(datetime.fromisoformat(value).utcoffset() == timedelta(0) for value in stamps)
    assert order["ordered_at"] == "2026-05-01T12:34:56+00:00"
    assert all(row["order_id"] is None for row in data.rows["stock_reservations"])
    assert data.rows["inventory_movements"][-1]["order_item_id"] is None
    skus = {row["sku"] for row in data.rows["inventory"]}
    assert all(row["sku"] in skus for name in ("order_items", "stock_reservations", "inventory_movements")
               for row in data.rows[name])
    assert all(row["provenance_kind"] for rows in data.rows.values() for row in rows)
    full = read_postgres(packet, read_catalog(packet, "demo"))
    assert full.rows["inventory_movements"][-1]["order_item_id"] == "line-c"
    assert full.counts()["orders"] == 3


def test_postgres_rejects_missing_source_reference_even_outside_ci(packet):
    path = packet / "tables/payments.csv"
    path.write_text(path.read_text().replace("order-c", "order-absent"), encoding="utf-8")
    with pytest.raises(DatasetError, match="order-absent"):
        read_postgres(packet, read_catalog(packet, "ci", ci_orders=2))


def test_postgres_rejects_empty_provenance_before_loading(packet):
    path = packet / "tables/inventory.csv"
    path.write_text(path.read_text().replace(",synthetic", ","), encoding="utf-8")
    with pytest.raises(DatasetError, match="provenance"):
        read_postgres(packet, read_catalog(packet, "demo"))


def test_postgres_import_sends_one_utf8_lf_transaction_and_reads_database_counts(packet, tmp_path, monkeypatch):
    data = read_postgres(packet, read_catalog(packet, "ci", ci_orders=2))
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, b'{"orders":2,"order_items":2,"payments":2,"inventory":2,'
                                          b'"stock_reservations":2,"inventory_movements":3}\n', b"")

    monkeypatch.setattr("data.demo.postgres.subprocess.run", run)
    assert import_postgres(data, tmp_path) == data.counts()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:8] == ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres"]
    assert "ON_ERROR_STOP=1" in args and not kwargs.get("text")
    script = kwargs["input"]
    assert isinstance(script, bytes) and b"\r" not in script
    assert (tmp_path / "postgres.sql").read_bytes() == script
    sql = script.decode("utf-8")
    assert sql.startswith("SET TIME ZONE 'UTC';\nBEGIN;\n") and sql.endswith("COMMIT;\n")
    assert sql.count("BEGIN;") == sql.count("COMMIT;") == 1
    tables = ["inventory.inventory_movements", "inventory.stock_reservations", "inventory.stock",
              "orders.order_lines", "orders.orders", "payment.payments"]
    deletes = [sql.index("DELETE FROM " + table + " WHERE provenance_kind IS NOT NULL;")  # noqa: S608 -- Constantes.
               for table in tables]
    assert deletes == sorted(deletes)
    assert sql.index("to_regclass") < min(deletes)
    copies = [sql.index("\\copy " + table + " (") for table in reversed(tables)]
    assert copies == sorted(copies) and max(deletes) < min(copies)
    assert all(name not in sql for name in ("saga_instances", "outbox", "idempotency_keys", "DISABLE"))
    # Le flux COPY garde aussi les valeurs dans le même ordre que ses colonnes.
    chunk = sql.split("\\copy orders.order_lines (", 1)[1]
    columns, content = chunk.split(") FROM STDIN WITH (FORMAT csv)\n", 1)
    row = next(csv.reader(content.splitlines()))
    assert dict(zip(columns.split(", "), row, strict=True))["unit_price_gbp"] == "3.25"
    assert "count(*)" in sql and "provenance_kind IS NOT NULL" in sql


def test_postgres_import_reports_missing_tables_without_continuing(packet, tmp_path):
    data = read_postgres(packet, read_catalog(packet, "demo"))

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 3, b"", b"Tables absentes : lancer make up")

    with pytest.raises(DatasetError, match="lancer make up"):
        import_postgres(data, tmp_path, run=run)


def test_postgres_import_refuses_database_count_mismatch(packet, tmp_path):
    data = read_postgres(packet, read_catalog(packet, "demo"))

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, b'{"orders":0}\n', b"")

    with pytest.raises(DatasetError, match="Comptes PostgreSQL"):
        import_postgres(data, tmp_path, run=run)
