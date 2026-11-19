import pytest
from market_auth.config import Settings
from pydantic import ValidationError


@pytest.fixture
def environment(monkeypatch):
    values = {
        "ENVIRONMENT": "local", "AUTH_DB_PASSWORD": "unit-db-password", "JWT_ISSUER": "unit-auth",
        "JWT_AUDIENCE": "unit-market", "JWT_PRIVATE_KEY_PATH": "/unused/private.pem",
        "JWT_PUBLIC_KEY_PATH": "/unused/public.pem", "DEMO_CLIENT_PASSWORD": "unit-client",
        "DEMO_SELLER_PASSWORD": "unit-seller", "DEMO_OPS_PASSWORD": "unit-ops",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def test_config_reads_exact_environment_names_and_non_secret_defaults(environment, monkeypatch):
    for key in (
        "JWT_TTL_SECONDS", "AUTH_MAX_FAILURES", "AUTH_FAILURE_WINDOW_SECONDS", "AUTH_FAILURE_MAX_ENTRIES",
        "AUTH_HASH_CONCURRENCY", "AUTH_HASH_MAX_WAITING", "AUTH_HASH_WAIT_TIMEOUT_SECONDS",
        "AUTH_HASH_RETRY_AFTER_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.model_validate({})
    assert settings.jwt_issuer == "unit-auth"
    assert settings.jwt_audience == "unit-market"
    assert settings.environment == "local"
    assert settings.jwt_ttl_seconds == 900
    assert settings.auth_max_failures == 10
    assert settings.auth_failure_window_seconds == 300
    assert settings.auth_failure_max_entries == 10000
    assert settings.auth_hash_concurrency == 2
    assert settings.auth_hash_max_waiting == 16
    assert settings.auth_hash_wait_timeout_seconds == 0.25
    assert settings.auth_hash_retry_after_seconds == 1
    assert settings.database_url().username == "auth_svc"
    assert settings.database_url().password == environment["AUTH_DB_PASSWORD"]
    assert "unit-db-password" not in repr(settings)


def test_missing_secret_is_required_and_errors_hide_inputs(environment, monkeypatch):
    monkeypatch.delenv("AUTH_DB_PASSWORD")
    with pytest.raises(ValidationError) as error:
        Settings.model_validate({})
    assert "unit-client" not in str(error.value)


def test_config_overrides_lifetime_and_throttle(environment, monkeypatch):
    monkeypatch.setenv("JWT_TTL_SECONDS", "60")
    monkeypatch.setenv("AUTH_MAX_FAILURES", "3")
    monkeypatch.setenv("AUTH_FAILURE_WINDOW_SECONDS", "15")
    settings = Settings.model_validate({})
    assert settings.jwt_ttl_seconds == 60
    assert settings.auth_max_failures == 3
    assert settings.auth_failure_window_seconds == 15


def test_config_reads_queue_limits_and_failure_capacity(environment, monkeypatch):
    values = {"AUTH_HASH_CONCURRENCY": "3", "AUTH_HASH_MAX_WAITING": "0",
              "AUTH_HASH_WAIT_TIMEOUT_SECONDS": "0.05", "AUTH_HASH_RETRY_AFTER_SECONDS": "2",
              "AUTH_FAILURE_MAX_ENTRIES": "50"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Settings.model_validate({})
    assert settings.auth_hash_concurrency == 3
    assert settings.auth_hash_max_waiting == 0
    assert settings.auth_hash_wait_timeout_seconds == 0.05
    assert settings.auth_hash_retry_after_seconds == 2
    assert settings.auth_failure_max_entries == 50
