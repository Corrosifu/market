"""Schémas `$jsonSchema` : un fichier par catégorie de produit, plus ceux des vendeurs et des offres.

Le validateur de la collection `products` accepte un document seulement s'il respecte le schéma de SA catégorie :
une branche `$or` par catégorie, qui lie la valeur du champ `category` au schéma du fichier du même nom.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from market_catalog.domain.model import is_valid_category_name

CategorySchemas = dict[str, dict[str, Any]]

# Origine d'un document du jeu de démonstration (ADR 0001), conservée telle quelle ; absente des fixtures.
PROVENANCE_KIND: dict[str, Any] = {"bsonType": "string", "minLength": 1, "maxLength": 64}

SELLER_SCHEMA: dict[str, Any] = {
    "bsonType": "object",
    "required": ["_id", "name", "created_at"],
    "additionalProperties": False,
    "properties": {
        "_id": {"bsonType": "string", "minLength": 1, "maxLength": 64},
        "name": {"bsonType": "string", "minLength": 1, "maxLength": 200},
        "created_at": {"bsonType": "date"},
        "provenance_kind": PROVENANCE_KIND,
    },
}

OFFER_SCHEMA: dict[str, Any] = {
    "bsonType": "object",
    "required": ["_id", "product_id", "seller_id", "price_cents", "currency", "created_at"],
    "additionalProperties": False,
    "properties": {
        "_id": {"bsonType": "string", "minLength": 1, "maxLength": 64},
        "product_id": {"bsonType": "string", "minLength": 1, "maxLength": 64},
        "seller_id": {"bsonType": "string", "minLength": 1, "maxLength": 64},
        "price_cents": {"bsonType": ["int", "long"], "minimum": 0},
        "currency": {"enum": ["GBP", "EUR"]},  # GBP : devise du jeu de démonstration, conservée
        "created_at": {"bsonType": "date"},
        "provenance_kind": PROVENANCE_KIND,
    },
}


class InvalidSchemaFile(ValueError):
    """Fichier de schéma inutilisable : le service refuse de démarrer plutôt que d'accepter n'importe quel produit."""


def load_category_schemas(directory: Path) -> CategorySchemas:
    """Lit `<categorie>.json` dans `directory` ; le nom du fichier est le nom de la catégorie."""
    schemas: CategorySchemas = {}
    for path in sorted(directory.glob("*.json")):
        name = path.stem
        if not is_valid_category_name(name):
            raise InvalidSchemaFile(f"{path.name} : nom de catégorie invalide")
        schema = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict) or schema.get("bsonType") != "object":
            raise InvalidSchemaFile(f"{path.name} : un schéma de produit doit être un objet (bsonType object)")
        schemas[name] = schema
    if not schemas:
        raise InvalidSchemaFile(f"aucun schéma de catégorie dans {directory}")
    return schemas


def products_validator(schemas: CategorySchemas) -> dict[str, Any]:
    """Validateur de `products` : la catégorie du document choisit le schéma ; catégorie inconnue, document refusé."""
    return {"$or": [{"category": name, "$jsonSchema": schema} for name, schema in sorted(schemas.items())]}
