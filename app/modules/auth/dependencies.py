from typing import Annotated, Any

import jwt
from fastapi import Depends
from fastapi.security import OAuth2AuthorizationCodeBearer
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.dependencies import DbSession

from .models import User
from .services import decode_access_token, provision_user, realm_roles
from .utils.exceptions import (
    AdminRequiredError,
    IdentityProviderUnavailableError,
    InactiveUserError,
    InvalidCredentialsError,
)

_oidc = f"{settings.keycloak_issuer}/protocol/openid-connect"
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{_oidc}/auth", tokenUrl=f"{_oidc}/token"
)


async def get_claims(token: Annotated[str, Depends(oauth2_scheme)]) -> dict[str, Any]:
    try:
        # PyJWKClient does blocking I/O when it fetches the keys.
        return await run_in_threadpool(decode_access_token, token)
    except jwt.PyJWKClientConnectionError:
        raise IdentityProviderUnavailableError from None
    except (jwt.PyJWKClientError, jwt.InvalidTokenError):  # unknown kid, bad signature, expired...
        raise InvalidCredentialsError from None


Claims = Annotated[dict[str, Any], Depends(get_claims)]


async def get_current_user(claims: Claims, db: DbSession) -> User:
    try:
        user = await provision_user(db, claims)
    except (KeyError, ValueError, AttributeError):  # no usable `email` or Keycloak `sub`
        raise InvalidCredentialsError from None
    if not user.is_active:
        raise InactiveUserError
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser, claims: Claims) -> User:
    if "admin" not in realm_roles(claims):
        raise AdminRequiredError
    return user


AdminUser = Annotated[User, Depends(require_admin)]
