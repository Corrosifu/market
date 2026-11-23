from contextlib import asynccontextmanager
from typing import cast

import httpx
import pytest
from market_payment.adapters.postgres import PostgresPayments
from market_payment.main import create_app
from sqlalchemy.ext.asyncio import AsyncEngine


class Rows:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def one(self):
        assert self.row is not None
        return self.row


class Database:
    def __init__(self):
        self.rows = {}

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, statement, params):
        sql = str(statement)
        if sql.startswith("INSERT"):
            assert "ON CONFLICT (order_id)" in sql and "DO NOTHING" in sql
            if params["order_id"] in self.rows:
                return Rows(None)
            self.rows[params["order_id"]] = params.copy()
            return Rows(params)
        assert sql.startswith("SELECT payment_id, status")
        return Rows(self.rows[params["order_id"]])


def client(environment="local"):
    database = Database()
    app = create_app()
    app.state.payments = PostgresPayments(cast(AsyncEngine, database))
    app.state.environment = environment
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), database


BODY = {"order_id": "order", "amount": "10.00", "currency": "GBP"}
HEADERS = {"Idempotency-Key": "order"}


@pytest.mark.anyio
async def test_same_idempotency_key_returns_same_payment():
    http, database = client()
    async with http:
        first = await http.post("/v1/payments", json=BODY, headers=HEADERS)
        replay = await http.post("/v1/payments", json=BODY, headers=dict(HEADERS, **{"X-Simulate-Failure": "payment"}))
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first.json()["status"] == "CAPTURED"
    assert len(database.rows) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("environment", ["production", "test", "staging", "LOCAL"])
async def test_simulated_failure_is_ignored_outside_local(environment):
    http, database = client(environment)
    async with http:
        result = await http.post("/v1/payments", json=BODY, headers=dict(HEADERS, **{"X-Simulate-Failure": "payment"}))
    assert result.status_code == 201
    assert result.json()["status"] == "CAPTURED"
    assert database.rows["order"]["status"] == "CAPTURED"


@pytest.mark.anyio
async def test_declined_payment_is_persisted_and_replayed_without_failure_header():
    http, database = client()
    async with http:
        first = await http.post("/v1/payments", json=BODY, headers=dict(HEADERS, **{"X-Simulate-Failure": "payment"}))
        replay = await http.post("/v1/payments", json=BODY, headers=HEADERS)
    assert first.status_code == replay.status_code == 402
    assert first.json() == replay.json() == {"status": "DECLINED"}
    assert len(database.rows) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "1.001", "10000000000.00"])
async def test_invalid_amount_never_reaches_database(amount):
    http, database = client()
    async with http:
        result = await http.post("/v1/payments", json=dict(BODY, amount=amount), headers=HEADERS)
    assert result.status_code == 422
    assert not database.rows


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [{}, {"Idempotency-Key": "other"}])
async def test_invalid_idempotency_key_never_reaches_database(headers):
    http, database = client()
    async with http:
        result = await http.post("/v1/payments", json=BODY, headers=headers)
    assert result.status_code == 422
    assert not database.rows


def test_openapi_matches_versioned_contract():
    import json
    from pathlib import Path

    contract = Path(__file__).resolve().parents[4] / "contracts/openapi/payment.json"
    assert create_app().openapi() == json.loads(contract.read_text())
