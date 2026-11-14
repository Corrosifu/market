"""Comportement des réglages communs : lecture de l'environnement, valeurs par défaut non secrètes."""
from __future__ import annotations

import pytest
from market_common.settings import BaseServiceSettings
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict


def test_settings_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "inventory")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ENVIRONMENT", "ci")

    settings = BaseServiceSettings()

    assert settings.service_name == "inventory"
    assert settings.log_level == "DEBUG"
    assert settings.environment == "ci"


def test_settings_have_non_secret_defaults_and_require_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SERVICE_NAME", "LOG_LEVEL", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        BaseServiceSettings()

    settings = BaseServiceSettings(service_name="order")
    assert settings.log_level == "INFO"
    assert settings.environment == "local"


def test_settings_do_not_read_a_dotenv_file_by_default(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SERVICE_NAME=from-dotenv\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        BaseServiceSettings()


class InventorySettings(BaseServiceSettings):
    model_config = SettingsConfigDict(env_prefix="INVENTORY_")
    db_pool_size: int = 5


def test_subclass_adds_prefixed_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVENTORY_SERVICE_NAME", "inventory")
    monkeypatch.setenv("INVENTORY_DB_POOL_SIZE", "12")

    settings = InventorySettings()

    assert settings.service_name == "inventory"
    assert settings.db_pool_size == 12


def test_shared_env_file_with_other_services_variables_is_tolerated(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Un service qui choisit explicitement un fichier partagé ne doit pas échouer sur les variables des autres.
    monkeypatch.delenv("INVENTORY_SERVICE_NAME", raising=False)
    shared = tmp_path / "shared.env"
    shared.write_text("INVENTORY_SERVICE_NAME=inventory\nPAYMENT_DB_POOL_SIZE=3\nKAFKA_TOPIC=x\n", encoding="utf-8")

    settings = InventorySettings(_env_file=shared)  # type: ignore[call-arg]

    assert settings.service_name == "inventory"
