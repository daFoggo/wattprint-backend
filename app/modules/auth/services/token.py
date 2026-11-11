from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import settings

# PyJWKClient caches the key set and refetches once when a token carries an unknown `kid`.
_jwks = PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600, timeout=5)


def decode_access_token(token: str) -> dict[str, Any]:
    """Return the verified claims, or raise jwt.InvalidTokenError. jwt.PyJWKClientConnectionError
    means Keycloak could not be reached, which is not the caller's fault."""
    key = _jwks.get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=settings.keycloak_audience,
        issuer=settings.keycloak_issuer,
        options={"require": ["exp", "sub", "iss", "aud"]},
    )
    # Only access tokens issued to our own app (not another client of the realm).
    if claims.get("typ") != "Bearer" or claims.get("azp") not in settings.client_id_list:
        raise jwt.InvalidTokenError("token was not issued to this app")
    return claims


def realm_roles(claims: dict[str, Any]) -> list[str]:
    access = claims.get("realm_access")
    roles = access.get("roles") if isinstance(access, dict) else None
    return [r for r in roles if isinstance(r, str)] if isinstance(roles, list) else []
