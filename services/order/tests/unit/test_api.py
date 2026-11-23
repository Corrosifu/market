import sqlite3
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest
from market_order.adapters.postgres import PostgresOrders
from market_order.domain.models import BodyMismatch, Line
from market_order.main import create_app


class Rows:
    def __init__(self, cursor):
        self.rows = [dict(row) for row in cursor.fetchall()]

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]

    def all(self):
        return self.rows


class Database:
    """Exécute les requêtes de lecture réelles : ni prédicat d'accès ni idempotence simulés."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            ATTACH ':memory:' AS orders;
            CREATE TABLE orders.orders (id TEXT, ordered_at TEXT, customer_id TEXT, status TEXT);
            INSERT INTO orders.orders VALUES ('ORD_SOURCE','2026-01-01','customer-source','CONFIRMED');
            CREATE TABLE orders.order_lines (id TEXT, order_id TEXT, sku TEXT, quantity INTEGER);
            INSERT INTO orders.order_lines VALUES ('line', 'ORD_SOURCE', 'sku', 2);
            CREATE TABLE orders.idempotency_keys (customer_id TEXT, key TEXT, fingerprint TEXT,
                order_id TEXT, response_code INTEGER, response_body TEXT, PRIMARY KEY (customer_id, key));
        """)

    @asynccontextmanager
    async def connect(self):
        yield self

    @asynccontextmanager
    async def begin(self):
        try:
            yield self
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    async def execute(self, statement, params=None):
        return Rows(self.db.execute(str(statement), params or {}))


@pytest.mark.anyio
async def test_get_order_of_another_customer_returns_404():
    app = create_app()
    app.state.orders = PostgresOrders(Database())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        path = "/v1/orders/ORD_SOURCE"
        assert (await http.get(path)).status_code == 401
        assert (await http.get(path, headers={"X-User-Id": "other"})).status_code == 404
        owner = await http.get(path, headers={"X-User-Id": "customer-source"})
        assert owner.status_code == 200
        assert owner.json() == {"id": "ORD_SOURCE", "status": "CONFIRMED", "lines": [{"sku": "sku", "quantity": 2}]}
        assert (await http.get(path, headers={"X-User-Id": "other", "X-User-Role": "ops"})).status_code == 200
        assert (await http.get("/v1/orders/missing", headers={"X-User-Id": "customer-source"})).status_code == 404
    # Aucune table saga n'existe : la lecture du paquet doit fonctionner sans elle.


@pytest.mark.anyio
async def test_same_idempotency_key_with_different_body_is_rejected():
    database = Database()
    database.db.execute("INSERT INTO orders.idempotency_keys VALUES ('client','key','other','order',NULL,NULL)")
    database.db.commit()
    with pytest.raises(BodyMismatch):
        await PostgresOrders(database).begin("client", "key", (Line("sku", 1),), Decimal("10.00"), False)


@pytest.mark.anyio
async def test_missing_key_is_400_and_missing_identity_is_401():
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        body = {"lines": [{"sku": "sku", "quantity": 1}]}
        assert (await http.post("/v1/orders", json=body)).status_code == 401
        assert (await http.post("/v1/orders", json=body, headers={"X-User-Id": "client"})).status_code == 400


@pytest.mark.anyio
@pytest.mark.parametrize(
    "lines",
    [
        [],
        [{"sku": "sku", "quantity": 0}],
        [{"sku": "sku", "quantity": True}],
        [{"sku": "sku", "quantity": -1}],
        [{"sku": "sku", "quantity": 1.5}],
    ],
)
async def test_invalid_lines_are_rejected_before_database_access(lines):
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        result = await http.post(
            "/v1/orders", json={"lines": lines}, headers={"X-User-Id": "client", "Idempotency-Key": "key"}
        )
    assert result.status_code == 422


def test_openapi_export_matches_versioned_contract_without_external_services(monkeypatch, tmp_path):
    import json
    from pathlib import Path

    from market_order.main import app
    from market_order.openapi import export

    monkeypatch.delenv("ORDERS_DB_PASSWORD", raising=False)
    contract = Path(__file__).resolve().parents[4] / "contracts/openapi/order.json"
    committed = contract.read_bytes()
    destination = tmp_path / "order.json"
    export(destination)
    generated = destination.read_bytes()
    assert generated == committed
    assert b"\r" not in generated
    assert app.openapi() == json.loads(committed)


@pytest.mark.anyio
async def test_matching_inflight_key_returns_conflict_from_persisted_row():
    from market_order.domain.models import Conflict, fingerprint

    database = Database()
    lines = (Line("sku", 1),)
    database.db.execute(
        "INSERT INTO orders.idempotency_keys VALUES (?,?,?,?,NULL,NULL)", ("client", "key", fingerprint(lines), "order")
    )
    database.db.commit()
    with pytest.raises(Conflict):
        await PostgresOrders(database).begin("client", "key", lines, Decimal("10.00"), False)
