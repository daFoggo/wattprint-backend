import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.modules.auth.services import token as security

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    """Resolve every token's signing key to the test key instead of calling Keycloak."""
    key = SimpleNamespace(key=_KEY.public_key())
    stub = SimpleNamespace(get_signing_key_from_jwt=lambda _t: key)
    monkeypatch.setattr(security, "_jwks", stub)


@pytest.fixture
def make_token():
    def make(*, sub=None, email=None, roles=(), key=_KEY, **overrides) -> str:
        now = int(time.time())
        claims = {
            "sub": sub or str(uuid.uuid4()),
            "email": f"user-{uuid.uuid4().hex[:8]}@example.com" if email is None else email,
            "name": "Test User",
            "typ": "Bearer",
            "azp": settings.client_id_list[0],
            "iss": settings.keycloak_issuer,
            "aud": settings.keycloak_audience,
            "iat": now,
            "exp": now + 300,
            "realm_access": {"roles": list(roles)},
        }
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})

    make.other_key = _OTHER_KEY
    return make


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
