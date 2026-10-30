"""JWT verification for tokens issued by the Better Auth service (jwt plugin).

The Expo client sends `Authorization: Bearer <jwt>` (authClient.token()). The signature is
checked against the service's public keys (JWKS), so no request goes to the auth service
per call. Keys are cached by PyJWKClient and refetched on an unknown `kid`.
"""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

_ALGORITHMS = ["EdDSA"]
_LEEWAY_SECONDS = 10


class AuthUser(BaseModel):
    id: str
    email: str
    name: str | None = None
    email_verified: bool = False


@lru_cache
def get_jwk_client() -> PyJWKClient:
    return PyJWKClient(settings.auth_jwks_url, cache_keys=True)


def _bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return token.strip()


async def get_current_user(
    request: Request, jwk_client: Annotated[PyJWKClient, Depends(get_jwk_client)]
) -> AuthUser:
    token = _bearer_token(request)
    try:
        # PyJWKClient does blocking network IO on a cache miss.
        signing_key = await run_in_threadpool(jwk_client.get_signing_key_from_jwt, token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            options={"require": ["exp", "sub", "iss", "aud"]},
            leeway=_LEEWAY_SECONDS,
        )
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Auth service unavailable"
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    return AuthUser(
        id=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name"),
        email_verified=bool(claims.get("emailVerified", False)),
    )


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
