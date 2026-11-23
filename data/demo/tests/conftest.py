import csv
import json

import pytest


@pytest.fixture
def packet(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()

    def write(name, rows):
        with (tables / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write("orders", [{"order_id": "order-" + value, "customer_id": "customer-" + value,
                      "ordered_at": "2026-05-01T12:34:56", "simulated_status": "DELIVERED",
                      "merchandise_total_gbp": "19.50", "provenance_kind": "synthetic_order"}
                     for value in "cab"])
    write("order_items", [{"order_item_id": "line-" + value, "order_id": "order-" + value,
                           "product_id": "PRD_" + value, "seller_id": "SELLER_SYN_" + seller,
                           "quantity": "6", "unit_price_gbp": "3.25", "provenance_kind": "derived"}
                          for value, seller in [("a", "extra"), ("b", "b"), ("c", "c")]])
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
    write("payments", [{"payment_id": "payment-" + v, "order_id": "order-" + v,
                        "shipment_id": "shipment-" + v, "payment_type": "CAPTURE", "method": "demo_card",
                        "amount_gbp": "19.50", "status": "SUCCEEDED", "payment_at": "2026-05-01T12:35:00",
                        "provenance_kind": "synthetic"} for v in "abc"])
    positions = [{"product_id": "PRD_" + v, "seller_id": "SELLER_SYN_" + seller, "hub_id": "unused"}
                 for v, seller in [("a", "extra"), ("b", "b"), ("c", "c")]]
    write("inventory", [r | {"available_quantity": "8", "reserved_quantity": "2", "on_hand_quantity": "10",
                            "snapshot_at": "2026-05-02T00:00:00", "provenance_kind": "synthetic"}
                        for r in positions])
    write("stock_reservations", [r | {"reservation_id": "reservation-" + v, "quantity": "2", "status": "RESERVED",
                                     "created_at": "2026-05-01T23:00:00", "provenance_kind": "synthetic"}
                                 for v, r in zip("abc", positions, strict=True)])
    movements = [r | {"movement_id": "movement-" + v, "order_item_id": "line-" + v,
                      "movement_type": "DISPATCH", "quantity_delta": "-6",
                      "occurred_at": "2026-05-01T13:00:00", "provenance_kind": "synthetic"}
                 for v, r in zip("abc", positions, strict=True)]
    movements.append(movements[0] | {"movement_id": "movement-excluded-line", "order_item_id": "line-c"})
    write("inventory_movements", movements)
    return tmp_path
