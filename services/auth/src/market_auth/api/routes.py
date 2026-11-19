"""Routes publiques de connexion et de JWKS, vérification interne de la gateway."""
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from market_auth.adapters.tokens import RsaTokens
from market_auth.application.login import LoginService
from market_auth.domain.identity import HashSaturated, InvalidCredentials, InvalidToken, LoginThrottled
from pydantic import BaseModel, Field, SecretStr

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    errors = [{key: value for key, value in error.items() if key not in {"input", "ctx"}}
              for error in cast(RequestValidationError, exc).errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)},
                        headers={"Cache-Control": "no-store"})


class LoginInput(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginOutput(BaseModel):
    access_token: str


def login_service(request: Request) -> LoginService:
    return cast(LoginService, request.app.state.login)


def token_service(request: Request) -> RsaTokens:
    return cast(RsaTokens, request.app.state.tokens)


@router.post("/v1/auth/login", response_model=LoginOutput, responses={401: {}, 429: {}, 503: {}})
async def login(
    body: LoginInput, response: Response, service: Annotated[LoginService, Depends(login_service)],
) -> LoginOutput:
    headers = {"Cache-Control": "no-store"}
    try:
        token = await service.login(body.email, body.password.get_secret_value())
    except InvalidCredentials:
        raise HTTPException(401, "Identifiants invalides", headers=headers) from None
    except LoginThrottled as exc:
        headers["Retry-After"] = str(exc.retry_after)
        raise HTTPException(429, "Trop de tentatives", headers=headers) from None
    except HashSaturated as exc:
        headers["Retry-After"] = str(exc.retry_after)
        raise HTTPException(503, "Authentification temporairement indisponible", headers=headers) from None
    response.headers.update(headers)
    return LoginOutput(access_token=token)


@router.get("/.well-known/jwks.json")
async def jwks(tokens: Annotated[RsaTokens, Depends(token_service)]) -> dict[str, list[dict[str, Any]]]:
    return tokens.jwks()


@router.get("/v1/auth/verify", status_code=204, responses={401: {}})
async def verify(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    tokens: Annotated[RsaTokens, Depends(token_service)],
) -> Response:
    try:
        if credentials is None:
            raise InvalidToken
        principal = tokens.verify(credentials.credentials)
    except InvalidToken:
        raise HTTPException(401, "Jeton invalide", headers={"WWW-Authenticate": "Bearer"}) from None
    return Response(status_code=204, headers={
        "X-User-Id": str(principal.id), "X-User-Role": principal.role.value, "Cache-Control": "no-store",
    })
