"""Le contrat versionné `contracts/openapi/catalog.json` est exactement celui que produit l'application."""
from __future__ import annotations

import json
from pathlib import Path

from market_catalog.openapi import openapi_document, render

CONTRACT = Path(__file__).resolve().parents[4] / "contracts" / "openapi" / "catalog.json"


def test_versioned_contract_matches_the_application() -> None:
    assert CONTRACT.read_text(encoding="utf-8") == render(openapi_document()), (
        "contrat périmé : uv run python -m market_catalog.openapi contracts/openapi/catalog.json"
    )


def test_product_creation_declares_its_refusals() -> None:
    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    responses = spec["paths"]["/v1/catalog/products"]["post"]["responses"]

    def schema(code: str) -> dict[str, object]:
        content: dict[str, object] = responses[code]["content"]["application/json"]["schema"]  # type: ignore[index]
        return content

    assert set(responses) >= {"201", "403", "422"}
    assert schema("403") == {"$ref": "#/components/schemas/ErrorOut"}
    assert schema("422") == {"anyOf": [{"$ref": "#/components/schemas/ErrorOut"},
                                       {"$ref": "#/components/schemas/HTTPValidationError"}]}
    assert {"ErrorOut", "HTTPValidationError"} <= set(spec["components"]["schemas"])


def test_contract_exposes_business_routes_under_v1_only() -> None:
    paths = set(json.loads(CONTRACT.read_text(encoding="utf-8"))["paths"])

    assert {"/v1/catalog/products", "/v1/catalog/graphql", "/healthz", "/readyz"} <= paths
    assert all(p.startswith("/v1/") or p in {"/healthz", "/readyz"} for p in paths)
