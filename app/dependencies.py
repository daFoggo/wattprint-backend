from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from .config import settings
from .database import get_session
from .models import User
from .security import decode_access_token, realm_roles
from .services.users import EmailTakenError, provision_user

DbSession = Annotated[AsyncSession, Depends(get_session)]

_oidc = f"{settings.keycloak_issuer}/protocol/openid-connect"
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{_oidc}/auth", tokenUrl=f"{_oidc}/token"
)

_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    "Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_claims(token: Annotated[str, Depends(oauth2_scheme)]) -> dict[str, Any]:
    try:
        # PyJWKClient does blocking I/O when it fetches the keys.
        return await run_in_threadpool(decode_access_token, token)
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Identity provider unreachable"
        ) from None
    except (jwt.PyJWKClientError, jwt.InvalidTokenError):  # unknown kid, bad signature, expired...
        raise _UNAUTHORIZED from None


Claims = Annotated[dict[str, Any], Depends(get_claims)]


async def get_current_user(claims: Claims, db: DbSession) -> User:
    try:
        user = await provision_user(db, claims)
    except (KeyError, ValueError, AttributeError):  # no usable `email`, or a `sub` not a UUID
        raise _UNAUTHORIZED from None
    except EmailTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email belongs to another account") from None
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser, claims: Claims) -> User:
    if "admin" not in realm_roles(claims):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
