"""Assemblage FastAPI, initialisé au démarrage et jamais à l'import."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from market_common import configure_logging, health_router

from market_auth.adapters.database import PostgresUsers, create_engine
from market_auth.adapters.passwords import ArgonPasswords
from market_auth.adapters.tokens import RsaTokens
from market_auth.api.routes import router, validation_error_handler
from market_auth.application.login import LoginService
from market_auth.config import Settings
from market_auth.domain.throttle import FailureLimiter
from market_auth.seed import restore_accounts


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.model_validate({})
    configure_logging(settings.service_name, settings.log_level)
    tokens = RsaTokens.from_files(
        settings.jwt_private_key_path, settings.jwt_public_key_path,
        settings.jwt_issuer, settings.jwt_audience, settings.jwt_ttl_seconds,
    )
    engine = create_engine(settings)
    try:
        users = PostgresUsers(engine)
        passwords = ArgonPasswords(
            settings.auth_hash_concurrency, max_waiting=settings.auth_hash_max_waiting,
            wait_timeout_seconds=settings.auth_hash_wait_timeout_seconds,
            retry_after_seconds=settings.auth_hash_retry_after_seconds,
        )
        await restore_accounts(settings, users, passwords)
        app.state.users = users
        app.state.tokens = tokens
        app.state.login = LoginService(users, passwords, tokens, FailureLimiter(
            settings.auth_max_failures, settings.auth_failure_window_seconds,
            max_keys=settings.auth_failure_max_entries,
        ))
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Market Auth", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    async def database_ready() -> bool:
        return await cast(PostgresUsers, app.state.users).ready()

    app.include_router(health_router({"postgres": database_ready}))
    app.include_router(router)
    return app


app = create_app()
