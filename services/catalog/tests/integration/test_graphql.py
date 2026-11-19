"""GraphQL du catalogue contre MongoDB : requêtes réellement comptées (pas de N+1), entrées bornées et typées."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from market_catalog.settings import GRAPHQL_MAX_ALIASES, GRAPHQL_MAX_DEPTH, GRAPHQL_MAX_TOKENS, MAX_PAGE_SIZE
from pymongo import monitoring
from pymongo.database import Database

NOW = datetime(2026, 11, 15, tzinfo=UTC)
SELLERS = [f"seller-{i}" for i in range(3)]
PRODUCT_COUNT = 12


class FindCounter(monitoring.CommandListener):
    """Compte les commandes `find` réellement envoyées à MongoDB, par collection."""

    def __init__(self) -> None:
        self.finds: Counter[str] = Counter()
        self.seller_filters: list[Any] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        if event.command_name == "find":
            collection = event.command["find"]
            self.finds[collection] += 1
            if collection == "sellers":
                self.seller_filters.append(event.command["filter"])

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass


@pytest.fixture
def counter() -> FindCounter:
    return FindCounter()


@pytest.fixture
def gql(app_factory: Any, counter: FindCounter, mongo_db: Database[dict[str, Any]]) -> Iterator[TestClient]:
    with app_factory(event_listeners=[counter]) as client:
        mongo_db.sellers.insert_many([{"_id": s, "name": f"Vendeur {s}", "created_at": NOW} for s in SELLERS])
        mongo_db.products.insert_many([
            {"_id": f"p-{i:02d}", "title": f"Livre {i}", "category": "books", "seller_id": SELLERS[i % 3],
             "created_at": NOW, "attributes": {"author": "A", "isbn": "9782070409189"}}
            for i in range(PRODUCT_COUNT)
        ])
        counter.finds.clear()
        yield client


def run(client: TestClient, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post("/v1/catalog/graphql", json={"query": query, "variables": variables or {}})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_products_expose_id_title_and_category(gql: TestClient) -> None:
    body = run(gql, "{ products(first: 3) { id title category } }")

    assert "errors" not in body
    assert body["data"]["products"] == [
        {"id": f"p-{i:02d}", "title": f"Livre {i}", "category": "books"} for i in range(3)
    ]


def test_products_can_be_filtered_by_category(gql: TestClient) -> None:
    body = run(gql, 'query($c: String) { products(category: $c, first: 5) { id } }', {"c": "electronics"})

    assert body == {"data": {"products": []}}


@pytest.mark.parametrize("first", [1, 5, PRODUCT_COUNT])
def test_sellers_are_loaded_in_one_batch_whatever_the_number_of_products(
    gql: TestClient, counter: FindCounter, first: int
) -> None:
    body = run(gql, "query($n: Int!) { products(first: $n) { id seller { id name } } }", {"n": first})

    assert "errors" not in body
    products = body["data"]["products"]
    assert len(products) == first
    assert all(p["seller"]["name"] == f"Vendeur {p['seller']['id']}" for p in products)
    # Une requête pour les produits, une seule pour tous leurs vendeurs : jamais une par produit.
    assert counter.finds == Counter({"products": 1, "sellers": 1})
    [seller_filter] = counter.seller_filters
    assert sorted(seller_filter["_id"]["$in"]) == sorted({SELLERS[i % 3] for i in range(first)})


@pytest.mark.parametrize("first", [0, -3, MAX_PAGE_SIZE + 1])
def test_first_outside_the_bound_is_an_error_without_query(gql: TestClient, counter: FindCounter, first: int) -> None:
    body = run(gql, "query($n: Int!) { products(first: $n) { id } }", {"n": first})

    assert body["errors"] and body["data"] is None
    assert counter.finds == Counter()


@pytest.mark.parametrize("category", [{"$ne": None}, ["books"], 1])
def test_non_string_category_is_rejected_before_any_query(
    gql: TestClient, counter: FindCounter, category: Any
) -> None:
    body = run(gql, "query($c: String) { products(category: $c) { id } }", {"c": category})

    assert body["errors"] and not body.get("data")
    assert counter.finds == Counter()


def test_operator_shaped_category_string_matches_nothing_or_is_refused(gql: TestClient) -> None:
    body = run(gql, 'query($c: String) { products(category: $c) { id } }', {"c": '{"$ne": null}'})

    assert not (body.get("data") or {}).get("products")


def test_deepest_legitimate_query_stays_within_the_depth_limit(gql: TestClient) -> None:
    # Le schéma actuel ne dépasse pas 3 niveaux (products > seller > name) : la limite de profondeur protège les
    # évolutions du schéma. Les champs d'introspection (`__schema`) sont ignorés par Strawberry pour la profondeur ;
    # leur coût est borné par le nombre de jetons (test ci-dessous).
    assert GRAPHQL_MAX_DEPTH >= 3

    body = run(gql, "{ products(first: 1) { seller { name } } }")

    assert "errors" not in body


def test_deep_introspection_query_is_bounded_by_the_token_limit(gql: TestClient) -> None:
    nested = "name " + "ofType { " * 400 + "name" + " }" * 400
    body = run(gql, f"{{ __schema {{ types {{ fields {{ type {{ {nested} }} }} }} }} }}")

    assert body["errors"] and not body.get("data")


def test_query_with_too_many_aliases_is_refused(gql: TestClient, counter: FindCounter) -> None:
    aliases = " ".join(f"a{i}: products(first: 1) {{ id }}" for i in range(GRAPHQL_MAX_ALIASES + 1))

    body = run(gql, f"{{ {aliases} }}")

    assert body["errors"] and not body.get("data")
    assert counter.finds == Counter()


def test_query_with_too_many_tokens_is_refused(gql: TestClient, counter: FindCounter) -> None:
    fields = " ".join(["id"] * GRAPHQL_MAX_TOKENS)

    body = run(gql, f"{{ products(first: 1) {{ {fields} }} }}")

    assert body["errors"] and not body.get("data")
    assert counter.finds == Counter()


def test_graphql_is_not_served_over_get(gql: TestClient, counter: FindCounter) -> None:
    response = gql.get("/v1/catalog/graphql", params={"query": "{ products(first: 1) { id } }"})

    assert response.status_code == 400
    assert counter.finds == Counter()
