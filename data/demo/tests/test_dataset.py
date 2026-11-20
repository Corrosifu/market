import csv
import json

import pytest

from data.demo.dataset import CREATED_AT, read_catalog
from data.demo.errors import DatasetError


@pytest.fixture
def packet(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()

    def write(name, rows):
        with (tables / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write("orders", [{"order_id": value} for value in ["order-c", "order-a", "order-b"]])
    write("order_items", [{"order_id": "order-" + value, "product_id": "PRD_" + value} for value in "abc"])
    write("sellers", [{"seller_id": "SELLER_SYN_" + value, "name": value,
                       "provenance_kind": "synthetic", "hub_id": "unused"} for value in ["a", "b", "c", "extra"]])
    write("offers", [{"offer_id": "OFFER_SYN_" + value, "product_id": "PRD_" + product,
                      "seller_id": "SELLER_SYN_" + seller, "provenance_kind": "synthetic", "hub_id": "unused"}
                     for value, product, seller in [("a", "a", "extra"), ("b", "b", "b"), ("c", "c", "c")]])
    products = [{"_id": "PRD_" + value, "name": value, "category_id": category,
                 "seller_ids": ["SELLER_SYN_" + value], "attributes": attributes,
                 "synthetic_brand": "Brand", "reference_price_gbp": "0.29", "provenance_kind": "synthetic",
                 "stock_code": "not-imported"}
                for value, category, attributes in [("a", "electronics", {"warranty_months": 12}),
                                                     ("b", "books", {"page_count": 100}), ("c", "toys", {})]]
    (tmp_path / "products.jsonl").write_text("\n".join(map(json.dumps, products)), encoding="utf-8")
    return tmp_path


def test_ci_selection_is_deterministic_and_closed_over_all_foreign_keys(packet):
    first = read_catalog(packet, "ci", ci_orders=2)
    assert first == read_catalog(packet, "ci", ci_orders=2)
    assert first.order_ids == ("order-a", "order-b")
    assert {p["_id"] for p in first.documents["products"]} == {"PRD_a", "PRD_b"}
    sellers = {s["_id"] for s in first.documents["sellers"]}
    assert sellers == {"SELLER_SYN_a", "SELLER_SYN_b", "SELLER_SYN_extra"}
    assert all(o["seller_id"] in sellers for o in first.documents["offers"])
    assert all(p["seller_id"] in sellers for p in first.documents["products"])
    assert first.counts() == {"orders": 2, "order_items": 2, "sellers": 3, "products": 2, "offers": 2}


def test_mapping_keeps_ids_provenance_dates_and_decimal_prices(packet):
    data = read_catalog(packet, "demo")
    product = data.documents["products"][0]
    assert product == {"_id": "PRD_a", "title": "a", "category": "electronics", "seller_id": "SELLER_SYN_a",
                       "attributes": {"warranty_months": 12, "brand": "Brand"}, "provenance_kind": "synthetic",
                       "created_at": {"$date": CREATED_AT}}
    offer = data.documents["offers"][0]
    assert offer["price_cents"] == 29 and offer["currency"] == "GBP"
    assert offer["_id"] == "OFFER_SYN_a" and offer["product_id"] == "PRD_a"
    for collection in data.documents.values():
        assert all(row["provenance_kind"] == "synthetic" and row["created_at"] == {"$date": CREATED_AT}
                   for row in collection)
        assert all("hub_id" not in row for row in collection)
    assert len(data.documents["products"]) == 3 and len(data.documents["sellers"]) == 4


def test_missing_foreign_key_is_an_error_instead_of_a_smaller_dataset(packet):
    (packet / "tables/order_items.csv").write_text("order_id,product_id\norder-a,PRD_absent\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="produit absent"):
        read_catalog(packet, "ci", ci_orders=1)
