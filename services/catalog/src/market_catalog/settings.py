"""Réglages du catalogue, lus de l'environnement (`ENVIRONMENT`, `MONGO_URL`), et bornes des entrées.

Les bornes sont des constantes de configuration : elles protègent le service (taille des pages, coût des requêtes
GraphQL) et ne sont pas des règles métier.
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

from market_common import BaseServiceSettings
from pydantic import SecretStr

# Taille de page : `first` hors de [1, MAX_PAGE_SIZE] est refusé (REST 422, GraphQL erreur), jamais tronqué en silence.
DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 50

# Imbrication des attributs d'un produit (`attributes` compris) : au-delà, 422.
MAX_ATTRIBUTE_DEPTH: Final = 4

# Coût d'une requête GraphQL : profondeur d'imbrication, jetons analysés, alias.
GRAPHQL_MAX_DEPTH: Final = 5
GRAPHQL_MAX_TOKENS: Final = 1000
GRAPHQL_MAX_ALIASES: Final = 10

# Délai de sélection du serveur MongoDB : une base injoignable échoue vite (démarrage, /readyz) au lieu de 30 s.
MONGO_SERVER_SELECTION_TIMEOUT_MS: Final = 2000

# Base utilisée si `MONGO_URL` n'en nomme aucune.
DEFAULT_DATABASE: Final = "catalog"

SCHEMAS_DIR: Final = Path(__file__).resolve().parents[2] / "schemas"


class CatalogSettings(BaseServiceSettings):
    """`MONGO_URL` est obligatoire et traité comme un secret : il pourra porter des identifiants."""

    service_name: str = "catalog"
    mongo_url: SecretStr
