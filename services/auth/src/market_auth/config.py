"""Variables injectées par compose, sans lecture de fichier d'environnement."""
from pathlib import Path

from market_common import BaseServiceSettings
from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)
    service_name: str = "auth"
    postgres_host: str = "postgres"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "market"
    auth_db_password: SecretStr = Field(validation_alias="AUTH_DB_PASSWORD")
    jwt_issuer: str = Field(validation_alias="JWT_ISSUER")
    jwt_audience: str = Field(validation_alias="JWT_AUDIENCE")
    jwt_private_key_path: Path = Field(validation_alias="JWT_PRIVATE_KEY_PATH")
    jwt_public_key_path: Path = Field(validation_alias="JWT_PUBLIC_KEY_PATH")
    jwt_ttl_seconds: int = Field(default=900, gt=0)
    demo_client_password: SecretStr = Field(validation_alias="DEMO_CLIENT_PASSWORD")
    demo_seller_password: SecretStr = Field(validation_alias="DEMO_SELLER_PASSWORD")
    demo_ops_password: SecretStr = Field(validation_alias="DEMO_OPS_PASSWORD")
    auth_max_failures: int = Field(default=10, gt=0)
    auth_failure_window_seconds: float = Field(default=300, gt=0)
    auth_failure_max_entries: int = Field(default=10000, gt=0)
    auth_hash_concurrency: int = Field(default=2, gt=0)
    auth_hash_max_waiting: int = Field(default=16, ge=0)
    auth_hash_wait_timeout_seconds: float = Field(default=0.25, gt=0, allow_inf_nan=False)
    auth_hash_retry_after_seconds: int = Field(default=1, gt=0)

    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg", username="auth_svc", password=self.auth_db_password.get_secret_value(),
            host=self.postgres_host, port=self.postgres_port, database=self.postgres_db,
        )
