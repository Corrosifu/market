"""Conversion des attributs du paquet vers les schémas du catalogue MongoDB."""
import copy
import json
import re
from pathlib import Path
from typing import Any

from data.demo.errors import DatasetError

BASE_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "title", "category", "seller_id", "attributes", "created_at"],
    "additionalProperties": False,
    "properties": {
        "_id": {"bsonType": "string", "minLength": 1, "maxLength": 64},
        "title": {"bsonType": "string", "minLength": 1, "maxLength": 200},
        "seller_id": {"bsonType": "string", "minLength": 1, "maxLength": 64},
        "description": {"bsonType": "string", "maxLength": 2000},
        "created_at": {"bsonType": "date"},
        "provenance_kind": {"bsonType": "string", "minLength": 1, "maxLength": 64},
    },
}
TYPES = {"integer": ["int", "long"], "number": ["int", "long", "double"],
         "boolean": "bool", "string": "string", "object": "object", "array": "array", "null": "null"}


def convert_fragment(schema: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in {"$schema", "$id", "format"}:
            continue
        if key == "type":
            if value not in TYPES:
                raise DatasetError(f"Type de schéma non pris en charge : {value}")
            result["bsonType"] = TYPES[value]
        elif key in {"properties", "patternProperties"}:
            result[key] = {name: convert_fragment(child) for name, child in value.items()}
        elif isinstance(value, dict):
            result[key] = convert_fragment(value)
        elif key in {"allOf", "anyOf", "oneOf"}:
            result[key] = [convert_fragment(child) for child in value]
        else:
            result[key] = copy.deepcopy(value)
    return result


def product_schema(category: str, source: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    result = copy.deepcopy(existing if existing is not None else BASE_SCHEMA)
    attributes = convert_fragment(source["properties"]["attributes"])
    if existing is not None:
        attributes["properties"].update(existing["properties"]["attributes"]["properties"])
        if category == "electronics":
            attributes["required"] = ["brand", "warranty_months"]
        else:
            attributes.pop("required", None)
    result["properties"]["attributes"] = attributes
    result["properties"]["category"] = {"enum": [category]}
    return result


def write_schemas(package: Path, destination: Path) -> None:
    files = sorted((package / "schemas").glob("product_*.schema.json"))
    if len(files) != 26:
        raise DatasetError(f"26 schémas attendus dans le paquet, {len(files)} trouvés")
    for path in files:
        category = path.name.removeprefix("product_").removesuffix(".schema.json")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", category):
            raise DatasetError(f"Nom de catégorie invalide : {category}")
        target = destination / f"{category}.json"
        existing = None
        if category in {"books", "electronics"}:
            existing = json.loads(target.read_text(encoding="utf-8"))
        result = product_schema(category, json.loads(path.read_text(encoding="utf-8")), existing)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
