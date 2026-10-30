import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.core.security import get_jwk_client
from app.main import app

ISSUER = "http://localhost:3000"
AUDIENCE = "wattprint-api"

PRIVATE_KEY = Ed25519PrivateKey.generate()
PUBLIC_KEY = PRIVATE_KEY.public_key()


class FakeJwkClient:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def get_signing_key_from_jwt(self, token: str):
        if self.error:
            raise self.error
        kid = jwt.get_unverified_header(token).get("kid")
        if kid != "k1":
            raise jwt.PyJWKClientError(f"Unable to find a signing key that matches: {kid}")
        return SimpleNamespace(key=PUBLIC_KEY)


def make_claims(**overrides):
    claims = {
        "sub": "user-1",
        "email": "a@example.com",
        "name": "An",
        "emailVerified": True,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def eddsa(claims, kid="k1"):
    return jwt.encode(claims, PRIVATE_KEY, algorithm="EdDSA", headers={"kid": kid})


@pytest.fixture
def client():
    app.dependency_overrides[get_jwk_client] = lambda: FakeJwkClient()
    yield TestClient(app)
    app.dependency_overrides.clear()


def get_me(client, authorization: str | None):
    headers = {"Authorization": authorization} if authorization is not None else {}
    return client.get("/api/v1/me", headers=headers)


def test_valid_token_returns_user(client):
    resp = get_me(client, f"Bearer {eddsa(make_claims())}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "user-1"
    assert body["email"] == "a@example.com"
    assert body["name"] == "An"
    assert body["email_verified"] is True


def test_user_without_name_is_ok(client):
    resp = get_me(client, f"Bearer {eddsa(make_claims(name=None, emailVerified=None))}")
    assert resp.status_code == 200
    assert resp.json()["name"] is None
    assert resp.json()["email_verified"] is False


def test_expired_token_401(client):
    token = eddsa(make_claims(exp=int(time.time()) - 600))
    assert get_me(client, f"Bearer {token}").status_code == 401


def test_wrong_audience_401(client):
    assert get_me(client, f"Bearer {eddsa(make_claims(aud='other'))}").status_code == 401


def test_wrong_issuer_401(client):
    assert get_me(client, f"Bearer {eddsa(make_claims(iss='http://evil'))}").status_code == 401


def test_unknown_kid_401(client):
    assert get_me(client, f"Bearer {eddsa(make_claims(), kid='unknown')}").status_code == 401


def test_hs256_token_401(client):
    token = jwt.encode(make_claims(), "x" * 32, algorithm="HS256", headers={"kid": "k1"})
    assert get_me(client, f"Bearer {token}").status_code == 401


def test_alg_none_401(client):
    token = jwt.encode(make_claims(), None, algorithm="none", headers={"kid": "k1"})
    assert get_me(client, f"Bearer {token}").status_code == 401


def test_missing_header_401(client):
    assert get_me(client, None).status_code == 401


def test_empty_bearer_401(client):
    assert get_me(client, "Bearer ").status_code == 401


def test_lowercase_bearer_scheme_200(client):
    assert get_me(client, f"bearer {eddsa(make_claims())}").status_code == 200


def test_jwks_unreachable_503():
    err = jwt.PyJWKClientConnectionError("down")
    app.dependency_overrides[get_jwk_client] = lambda: FakeJwkClient(error=err)
    try:
        resp = get_me(TestClient(app), f"Bearer {eddsa(make_claims())}")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 503
