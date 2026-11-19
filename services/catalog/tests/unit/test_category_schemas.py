"""Chargement des schémas de catégorie et construction du validateur de `products`, sans MongoDB."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from market_catalog.adapters.schemas import InvalidSchemaFile, load_category_schemas, products_validator
from market_catalog.settings import SCHEMAS_DIR

UNSUPPORTED_BY_MONGODB = {"$schema", "$id", "format"}


def keys_of(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for value in node.values() for k in keys_of(value)}
    if isinstance(node, list):
        return {k for value in node for k in keys_of(value)}
    return set()


def test_versioned_schemas_use_only_the_mongodb_subset() -> None:
    schemas = load_category_schemas(SCHEMAS_DIR)

    assert {"electronics", "books"} <= set(schemas)
    for name, schema in schemas.items():
        assert not keys_of(schema) & UNSUPPORTED_BY_MONGODB, name
        assert schema["properties"]["category"] == {"enum": [name]}


def test_validator_binds_each_category_to_its_own_schema() -> None:
    schemas = {"books": {"bsonType": "object", "title": "b"}, "electronics": {"bsonType": "object", "title": "e"}}

    validator = products_validator(schemas)

    assert validator == {"$or": [
        {"category": "books", "$jsonSchema": schemas["books"]},
        {"category": "electronics", "$jsonSchema": schemas["electronics"]},
    ]}


@pytest.mark.parametrize(("filename", "content"), [
    ("Bad-Name.json", {"bsonType": "object"}),
    ("toys.json", {"bsonType": "string"}),
])
def test_unusable_schema_file_prevents_startup(tmp_path: Path, filename: str, content: dict[str, Any]) -> None:
    (tmp_path / filename).write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(InvalidSchemaFile):
        load_category_schemas(tmp_path)


def test_missing_schemas_prevent_startup(tmp_path: Path) -> None:
    with pytest.raises(InvalidSchemaFile):
        load_category_schemas(tmp_path)
