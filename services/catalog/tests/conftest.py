"""Fixtures des tests du catalogue.

Les tests d'intégration ont besoin d'un vrai MongoDB :
- `CATALOG_TEST_MONGO_URL` défini (par exemple `mongodb://127.0.0.1:27017`, publié par la pile `core`) : ce serveur ;
- sinon, un conteneur `mongo:7.0.18` (même tag que le compose) démarré une fois par session de tests par
  testcontainers, puis arrêté. Docker absent : échec explicite, jamais un test sauté.
Chaque test reçoit une base dédiée, créée vide puis supprimée.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient
from market_catalog.main import create_app
from market_catalog.settings import CatalogSettings
from pydantic import SecretStr
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

MONGO_TEST_IMAGE = "mongo:7.0.18"


def database_url(server_url: str, name: str) -> str:
    """URL du serveur pointant la base `name` ; avec identifiants, ceux-ci restent vérifiés dans `admin`."""
    parts = urlsplit(server_url)
    query = dict(parse_qsl(parts.query))
    if "@" in parts.netloc:
        query.setdefault("authSource", "admin")
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", urlencode(query), ""))


@pytest.fixture(scope="session")
def mongo_server() -> Iterator[str]:
    """URL d'un serveur MongoDB joignable pour toute la session."""
    configured = os.environ.get("CATALOG_TEST_MONGO_URL")
    if configured:
        yield configured
        return
    from testcontainers.community.mongodb import MongoDbContainer

    try:
        container = MongoDbContainer(MONGO_TEST_IMAGE)  # le constructeur contacte déjà le démon Docker
        container.start()
    except Exception as err:  # Docker absent ou injoignable : on échoue avec la cause, sans sauter le test
        pytest.fail(f"MongoDB de test impossible à démarrer ({MONGO_TEST_IMAGE}) : Docker est-il lancé ? "
                    f"Ou définir CATALOG_TEST_MONGO_URL. Cause : {err.__class__.__name__}: {err}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def mongo_url(mongo_server: str) -> Iterator[str]:
    """URL d'une base de test vide, propre au test, supprimée à la fin."""
    name = f"catalog_test_{uuid.uuid4().hex[:12]}"
    admin: MongoClient[dict[str, object]] = MongoClient(mongo_server, serverSelectionTimeoutMS=5000)
    try:
        admin.admin.command("ping")
    except PyMongoError as err:
        admin.close()
        pytest.fail(f"MongoDB de test injoignable : {err.__class__.__name__}")
    try:
        yield database_url(mongo_server, name)
    finally:
        admin.drop_database(name)
        admin.close()


@pytest.fixture
def mongo_db(mongo_url: str) -> Iterator[Database[dict[str, Any]]]:
    """Accès direct (synchrone) à la base de test, pour préparer et observer les données."""
    client: MongoClient[dict[str, Any]] = MongoClient(mongo_url, tz_aware=True)
    yield client.get_default_database()
    client.close()


AppFactory = Callable[..., TestClient]


@pytest.fixture
def app_factory(mongo_url: str) -> AppFactory:
    """Application complète (lifespan compris) contre la base de test. `environment` vaut `test` par défaut :
    les fixtures de démarrage, réservées à `local`, ne viennent pas fausser les comptes des tests."""

    def build(environment: str = "test", **app_kwargs: Any) -> TestClient:
        settings = CatalogSettings(mongo_url=SecretStr(mongo_url), environment=environment)
        return TestClient(create_app(settings, **app_kwargs))

    return build


@pytest.fixture
def api(app_factory: AppFactory) -> Iterator[TestClient]:
    with app_factory() as client:
        yield client
