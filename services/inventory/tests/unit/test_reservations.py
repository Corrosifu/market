import copy
from contextlib import asynccontextmanager
from typing import cast

import httpx
import pytest
from market_inventory.adapters.postgres import PostgresInventory
from market_inventory.domain.model import InsufficientStock, Line, ReservationConflict, Status
from market_inventory.main import create_app
from sqlalchemy.ext.asyncio import AsyncEngine


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class TransactionalDatabase:
    """Double transactionnel qui refuse une lecture du stock avant son UPDATE."""

    def __init__(self):
        self.stock = {"a": {"available": 3, "reserved": 0}, "b": {"available": 0, "reserved": 0}}
        self.reservations = []
        self.movements = []
        self.updates = []

    @asynccontextmanager
    async def begin(self):
        before = copy.deepcopy((self.stock, self.reservations, self.movements))
        try:
            yield self
        except BaseException:
            self.stock, self.reservations, self.movements = before
            raise

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        assert not (sql.startswith("SELECT") and "FROM inventory.stock " in sql), "Lecture puis écriture interdite"
        if sql.startswith("SELECT pg_advisory"):
            return Result()
        if sql.startswith("SELECT") and "FROM inventory.stock_reservations" in sql:
            return Result(
                sorted(
                    (r for r in self.reservations if r["order_id"] == params["order_id"]), key=lambda row: row["sku"]
                )
            )
        if sql.startswith("UPDATE inventory.stock SET available = available -"):
            assert "available >= :q" in sql, "La garde doit être évaluée par l'UPDATE"
            self.updates.append(params["sku"])
            row = self.stock.get(params["sku"])
            if row is None or row["available"] < params["q"]:
                return Result()
            row["available"] -= params["q"]
            row["reserved"] += params["q"]
            return Result([{"product_id": None, "seller_id": None, "hub_id": None}])
        if sql.startswith("UPDATE inventory.stock SET reserved = reserved -"):
            row = self.stock[params["sku"]]
            if row["reserved"] < params["q"]:
                return Result()
            row["reserved"] -= params["q"]
            if "available = available +" in sql:
                row["available"] += params["q"]
            return Result([{"sku": params["sku"]}])
        if sql.startswith("INSERT INTO inventory.stock_reservations"):
            self.reservations.append(dict(params, quantity=params["q"], status="RESERVED"))
            return Result()
        if sql.startswith("UPDATE inventory.stock_reservations"):
            for row in self.reservations:
                if row["order_id"] == params["order_id"]:
                    row["status"] = params["status"]
            return Result()
        if sql.startswith("INSERT INTO inventory.inventory_movements"):
            self.movements.append(dict(params))
            return Result()
        raise AssertionError(f"Instruction non prévue : {sql}")


@pytest.mark.anyio
async def test_reserve_refuses_when_available_is_insufficient():
    database = TransactionalDatabase()
    repository = PostgresInventory(database)
    with pytest.raises(InsufficientStock):
        await repository.reserve("order", (Line("a", 2), Line("b", 1)))
    assert database.updates == ["a", "b"]
    assert database.stock == {"a": {"available": 3, "reserved": 0}, "b": {"available": 0, "reserved": 0}}
    assert not database.reservations and not database.movements


@pytest.mark.anyio
async def test_reservation_replay_and_duplicate_lines_have_one_effect():
    database = TransactionalDatabase()
    repository = PostgresInventory(database)
    first = await repository.reserve("order", (Line("a", 1), Line("a", 1)))
    replay = await repository.reserve("order", (Line("a", 2),))
    assert replay == first and database.stock["a"] == {"available": 1, "reserved": 2}
    assert database.updates == ["a"]
    with pytest.raises(ReservationConflict):
        await repository.reserve("order", (Line("a", 3),))


@pytest.mark.anyio
@pytest.mark.parametrize("terminal", [Status.CONFIRMED, Status.RELEASED])
async def test_terminal_transitions_are_idempotent_and_cannot_be_reversed(terminal):
    database = TransactionalDatabase()
    repository = PostgresInventory(database)
    await repository.reserve("order", (Line("a", 2),))
    await repository.finish("order", terminal)
    expected = copy.deepcopy(database.stock)
    movement_count = len(database.movements)
    await repository.finish("order", terminal)
    assert database.stock == expected and len(database.movements) == movement_count
    opposite = Status.RELEASED if terminal == Status.CONFIRMED else Status.CONFIRMED
    with pytest.raises(ReservationConflict):
        await repository.finish("order", opposite)
    assert database.stock == expected


@pytest.mark.anyio
async def test_releasing_an_unknown_order_has_no_effect():
    database = TransactionalDatabase()
    await PostgresInventory(database).finish("unknown", Status.RELEASED)
    assert not database.reservations and not database.movements


def client():
    database = TransactionalDatabase()
    app = create_app()
    app.state.inventory = PostgresInventory(cast(AsyncEngine, database))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), database


@pytest.mark.anyio
@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "1", 2147483648])
async def test_invalid_quantity_does_not_touch_stock(quantity):
    http, database = client()
    async with http:
        result = await http.post(
            "/v1/reservations", json={"order_id": "order", "lines": [{"sku": "a", "quantity": quantity}]}
        )
    assert result.status_code == 422
    assert database.updates == []


@pytest.mark.anyio
async def test_reservation_routes_replay_and_reject_opposite_terminal_transition():
    http, database = client()
    body = {"order_id": "order", "lines": [{"sku": "a", "quantity": 2}]}
    async with http:
        first = await http.post("/v1/reservations", json=body)
        replay = await http.post("/v1/reservations", json=body)
        assert first.status_code == replay.status_code == 201
        assert first.json() == replay.json()
        assert (await http.post("/v1/reservations/order/confirm")).status_code == 204
        assert (await http.post("/v1/reservations/order/confirm")).status_code == 204
        assert (await http.post("/v1/reservations/order/release")).status_code == 409
        assert (await http.post("/v1/reservations/unknown/release")).status_code == 204
    assert database.stock["a"] == {"available": 1, "reserved": 0}


@pytest.mark.anyio
async def test_missing_second_line_returns_conflict_without_stock_effect():
    http, database = client()
    async with http:
        result = await http.post(
            "/v1/reservations",
            json={"order_id": "order", "lines": [{"sku": "a", "quantity": 1}, {"sku": "b", "quantity": 1}]},
        )
    assert result.status_code == 409
    assert database.stock["a"] == {"available": 3, "reserved": 0}


@pytest.mark.anyio
async def test_empty_reservation_is_rejected_and_unknown_confirmation_returns_404():
    http, database = client()
    async with http:
        assert (await http.post("/v1/reservations", json={"order_id": "order", "lines": []})).status_code == 422
        assert (await http.post("/v1/reservations/unknown/confirm")).status_code == 404
    assert not database.updates


def test_openapi_matches_versioned_contract():
    import json
    from pathlib import Path

    contract = Path(__file__).resolve().parents[4] / "contracts/openapi/inventory.json"
    assert create_app().openapi() == json.loads(contract.read_text())
