from decimal import Decimal
from typing import Self

from market_common import BaseServiceSettings
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import SettingsConfigDict
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)
    service_name: str = "order"
    environment: str = "local"
    postgres_host: str = "postgres"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "market"
    orders_db_password: SecretStr = Field(validation_alias="ORDERS_DB_PASSWORD")
    inventory_url: str = "http://inventory:8000"
    payment_url: str = "http://payment:8000"
    kafka_bootstrap_servers: str = "kafka:9092"
    payment_timeout_seconds: float = Field(default=1, gt=0, allow_inf_nan=False)
    inventory_timeout_seconds: float = Field(default=1, gt=0, allow_inf_nan=False)
    retry_attempts: int = Field(default=3, ge=1)
    retry_backoff_seconds: float = Field(default=0.1, ge=0, le=0.2, allow_inf_nan=False)
    breaker_failure_threshold: int = Field(default=3, ge=1)
    breaker_reset_seconds: float = Field(default=5, gt=0, allow_inf_nan=False)
    bulkhead_max_concurrent: int = Field(default=20, ge=1)
    saga_stuck_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    saga_recovery_interval_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    order_stub_unit_price_gbp: Decimal = Field(default=Decimal("10.00"), gt=0, max_digits=12, decimal_places=2)
    outbox_poll_seconds: float = Field(default=1, gt=0, allow_inf_nan=False)
    kafka_delivery_timeout_seconds: float = Field(default=5, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_resilience(self) -> Self:
        if self.breaker_failure_threshold > self.retry_attempts:
            raise ValueError("BREAKER_FAILURE_THRESHOLD doit être <= RETRY_ATTEMPTS")
        return self

    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username="orders_svc",
            password=self.orders_db_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url(), pool_pre_ping=True, hide_parameters=True)
