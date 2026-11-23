import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from market_order.domain.models import Line, Reason, Saga, event


@pytest.mark.parametrize("confirmed", [True, False])
def test_event_shape_and_versioned_schema_agree(confirmed):
    saga = Saga("order", datetime.now(UTC), "customer", (Line("sku", 3),), Decimal("30.00"), "owner")
    envelope = event(saga, confirmed, None if confirmed else Reason.PAYMENT_DECLINED)
    name = "OrderConfirmed" if confirmed else "OrderCancelled"
    path = Path(__file__).resolve().parents[4] / f"contracts/events/{name}.v1.json"
    schema = json.loads(path.read_text())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(envelope) == set(schema["required"])
    UUID(envelope["event_id"])
    assert datetime.fromisoformat(envelope["occurred_at"]).utcoffset().total_seconds() == 0
    assert envelope["event_type"] == schema["properties"]["event_type"]["const"] == name
    assert envelope["schema_version"] == 1
    payload = envelope["payload"]
    assert set(payload) == set(schema["properties"]["payload"]["required"])
    assert payload["order_id"] == "order"
    if confirmed:
        assert payload["customer_id"] == "customer"
        assert payload["lines"] == [{"sku": "sku", "quantity": 3}]
        assert payload["total_gbp"] == "30.00" and isinstance(payload["total_gbp"], str)
    else:
        assert payload["reason"] in schema["properties"]["payload"]["properties"]["reason"]["enum"]
