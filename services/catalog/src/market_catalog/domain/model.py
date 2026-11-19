"""Modèle du catalogue et règles d'entrée, sans dépendance d'infrastructure."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SELLER_ROLE = "seller"

# Nom de catégorie : celui du fichier `schemas/<categorie>.json`. Une chaîne simple, jamais un opérateur MongoDB.
CATEGORY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_CATEGORY_RE = re.compile(CATEGORY_PATTERN)


class CatalogError(Exception):
    """Erreur métier du catalogue, traduite en code HTTP ou en erreur GraphQL par l'API."""


class InvalidRequest(CatalogError):
    """Entrée hors des bornes ou mal formée."""


class NotASeller(CatalogError):
    """Seul un utilisateur de rôle `seller` crée un produit."""


class UnknownSeller(CatalogError):
    """L'utilisateur a le rôle `seller` mais aucun vendeur ne lui correspond."""


class UnknownCategory(CatalogError):
    """Aucun schéma n'existe pour cette catégorie."""


class ProductRejected(CatalogError):
    """Le document ne respecte pas le schéma de sa catégorie (refus du validateur MongoDB)."""


@dataclass(frozen=True)
class Seller:
    id: str
    name: str


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    category: str
    seller_id: str
    created_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)
    description: str | None = None


@dataclass(frozen=True)
class Offer:
    id: str
    product_id: str
    seller_id: str
    price_cents: int
    currency: str
    created_at: datetime


def is_valid_category_name(name: object) -> bool:
    return isinstance(name, str) and _CATEGORY_RE.fullmatch(name) is not None


def check_category(category: object) -> str:
    if not isinstance(category, str) or _CATEGORY_RE.fullmatch(category) is None:
        raise InvalidRequest("catégorie invalide")
    return category


def check_page_size(first: object, maximum: int) -> int:
    # bool est un int en Python : True ne doit pas valoir 1.
    if isinstance(first, bool) or not isinstance(first, int) or not 1 <= first <= maximum:
        raise InvalidRequest(f"first doit être un entier entre 1 et {maximum}")
    return first


INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1


def check_attributes(attributes: object, max_depth: int) -> None:
    """Refuse des attributs qu'on ne peut ni stocker ni interroger sans risque :
    clés en forme d'opérateur ou de chemin MongoDB (`$…`, `a.b`), imbrication au-delà de `max_depth` niveaux
    (`attributes` compris), entiers hors de 64 bits (non encodables en BSON)."""

    def walk(value: object, depth: int) -> None:
        if isinstance(value, Mapping | list):
            if depth > max_depth:
                raise InvalidRequest(f"attributs imbriqués sur plus de {max_depth} niveaux")
            items = value.items() if isinstance(value, Mapping) else enumerate(value)
            for key, item in items:
                if isinstance(value, Mapping) and (not isinstance(key, str) or not key or key.startswith("$")
                                                   or "." in key or "\x00" in key):
                    raise InvalidRequest("nom d'attribut invalide")
                walk(item, depth + 1)
        elif isinstance(value, int) and not isinstance(value, bool) and not INT64_MIN <= value <= INT64_MAX:
            raise InvalidRequest("entier d'attribut hors de 64 bits")

    walk(attributes, 1)
