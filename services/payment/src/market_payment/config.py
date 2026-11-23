from market_common import BaseServiceSettings
from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)
    service_name: str = "payment"
    postgres_host: str = "postgres"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "market"
    payment_db_password: SecretStr = Field(validation_alias="PAYMENT_DB_PASSWORD")

    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username="payment_svc",
            password=self.payment_db_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url(), pool_pre_ping=True, hide_parameters=True)
