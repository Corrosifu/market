import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from market_auth.application.login import LoginService
from market_auth.domain.throttle import FailureLimiter
from market_auth.main import create_app


@pytest.fixture
def client(users, passwords, tokens):
    app = create_app()
    app.state.tokens = tokens
    app.state.login = LoginService(users, passwords, tokens, FailureLimiter(10, 300))
    # Les adaptateurs sont injectés, la durée de vie de la base est testée avec Docker.
    client = TestClient(app)
    yield client
    client.close()


@pytest.mark.anyio
async def test_login_returns_token_without_cache(client, client_user, tokens):
    response = client.post("/v1/auth/login", json={"email": " CLIENT@market.test ", "password": "unit-pass"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert tokens.verify(response.json()["access_token"]) == client_user.principal


@pytest.mark.anyio
async def test_credentials_errors_have_identical_http_response(client, client_user):
    responses = [client.post("/v1/auth/login", json={"email": email, "password": "wrong"})
                 for email in (client_user.email, "unknown@market.test")]
    assert [response.status_code for response in responses] == [401, 401]
    assert responses[0].json() == responses[1].json() == {"detail": "Identifiants invalides"}


def test_throttled_response_includes_retry_after(client):
    for _ in range(10):
        assert client.post("/v1/auth/login", json={"email": "unknown", "password": "wrong"}).status_code == 401
    response = client.post("/v1/auth/login", json={"email": " UNKNOWN ", "password": "wrong"})
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 300


@pytest.mark.anyio
async def test_verify_returns_only_trusted_identity_headers(client, client_user, tokens):
    response = client.get("/v1/auth/verify", headers={
        "Authorization": "Bearer " + tokens.issue(client_user.principal),
        "X-User-Role": "ops", "X-User-Id": "attacker",
    })
    assert response.status_code == 204 and not response.content
    assert response.headers["x-user-id"] == str(client_user.principal.id)
    assert response.headers["x-user-role"] == "client"


@pytest.mark.parametrize("authorization", ["", "Bearer nonsense", "Basic nonsense"])
def test_verify_refuses_invalid_authorization(client, authorization):
    response = client.get("/v1/auth/verify", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_public_jwks_requires_no_token(client, tokens):
    response = client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    assert response.json() == tokens.jwks()


def test_login_accepts_post_only_and_bounds_input(client):
    assert client.get("/v1/auth/login").status_code == 405
    assert client.post("/v1/auth/login", json={"email": "x" * 255, "password": "wrong"}).status_code == 422


def test_validation_errors_do_not_echo_password_or_pydantic_context(client):
    submitted = "sensitive-input-" * 100
    response = client.post("/v1/auth/login", json={"email": "client@market.test", "password": submitted})
    assert response.status_code == 422
    assert submitted not in response.text
    errors = response.json()["detail"]
    assert errors and errors[0]["loc"] == ["body", "password"]
    assert all("input" not in error and "ctx" not in error for error in errors)


def test_health_is_reused_from_market_common(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_exported_openapi_matches_the_running_routes():
    contract = Path(__file__).resolve().parents[4] / "contracts/openapi/auth.json"
    assert json.loads(contract.read_text(encoding="utf-8")) == create_app().openapi()
