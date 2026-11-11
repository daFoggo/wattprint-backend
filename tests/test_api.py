import asyncio
import uuid
from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import User
from app.modules.auth.services import token as security


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_openapi_exposes_authorization_code_flow(client):
    spec = (await client.get("/openapi.json")).json()
    flows = spec["components"]["securitySchemes"]["OAuth2AuthorizationCodeBearer"]["flows"]
    assert flows["authorizationCode"]["tokenUrl"].endswith("/protocol/openid-connect/token")


async def test_me_requires_token(client):
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_first_request_provisions_user_from_token(client, make_token):
    sub = str(uuid.uuid4())
    tag = uuid.uuid4().hex[:8]
    token = make_token(sub=sub, email=f"New.{tag}@Example.com", roles=["user"])
    r = await client.get("/api/v1/users/me", headers=bearer(token))
    assert r.status_code == 200
    body = r.json()
    assert uuid.UUID(body["id"]).version == 7
    assert body["email"] == f"new.{tag}@example.com"
    assert body["full_name"] == "Test User"
    assert body["roles"] == ["user"]
    # Second call reuses the same row.
    assert (await client.get("/api/v1/users/me", headers=bearer(token))).json()["id"] == body["id"]
    async with SessionLocal() as session:
        assert await session.scalar(select(User.id).where(User.keycloak_sub == sub)) == uuid.UUID(
            body["id"]
        )


async def test_concurrent_first_requests_create_one_user(client, make_token):
    token = make_token()
    results = await asyncio.gather(
        *(client.get("/api/v1/users/me", headers=bearer(token)) for _ in range(4))
    )
    assert [r.status_code for r in results] == [200] * 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": 1},  # expired
        {"iss": "http://evil.example/realms/wattprint"},
        {"aud": "account"},  # minted for another audience
        {"azp": "other-client"},
        {"typ": "ID"},
        {"sub": ""},
        {"email": ""},  # no usable email
    ],
)
async def test_bad_claims_rejected(client, make_token, overrides):
    # Control: the same token without the override is accepted.
    assert (await client.get("/api/v1/users/me", headers=bearer(make_token()))).status_code == 200
    r = await client.get("/api/v1/users/me", headers=bearer(make_token(**overrides)))
    assert r.status_code == 401


async def test_web_client_token_is_accepted(client, make_token):
    r = await client.get("/api/v1/users/me", headers=bearer(make_token(azp="wattprint-web")))
    assert r.status_code == 200


async def test_token_signed_with_other_key_rejected(client, make_token):
    r = await client.get("/api/v1/users/me", headers=bearer(make_token(key=make_token.other_key)))
    assert r.status_code == 401


async def test_garbage_token_rejected(client):
    r = await client.get("/api/v1/users/me", headers=bearer("not.a.jwt"))
    assert r.status_code == 401


async def test_hs256_token_rejected(client, make_token):
    forged = jwt.encode({"sub": str(uuid.uuid4()), "email": "a@example.com"}, "x" * 32, "HS256")
    assert (await client.get("/api/v1/users/me", headers=bearer(forged))).status_code == 401


async def test_inactive_user_rejected(client, make_token):
    sub = str(uuid.uuid4())
    token = make_token(sub=sub)
    assert (await client.get("/api/v1/users/me", headers=bearer(token))).status_code == 200
    async with SessionLocal() as session:
        await session.execute(update(User).where(User.keycloak_sub == sub).values(is_active=False))
        await session.commit()
    assert (await client.get("/api/v1/users/me", headers=bearer(token))).status_code == 403


async def test_email_of_another_account_conflicts(client, make_token):
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    assert (
        await client.get("/api/v1/users/me", headers=bearer(make_token(email=email)))
    ).status_code == 200
    r = await client.get("/api/v1/users/me", headers=bearer(make_token(email=email)))
    assert r.status_code == 409


async def test_users_list_is_admin_only(client, make_token):
    r = await client.get("/api/v1/users", headers=bearer(make_token(roles=["user"])))
    assert r.status_code == 403
    r = await client.get("/api/v1/users", headers=bearer(make_token(roles=["admin"])))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_unknown_kid_is_401_and_unreachable_keycloak_is_503(client, make_token, monkeypatch):
    def unknown_kid(_token):
        raise jwt.PyJWKClientError("Unable to find a signing key that matches")

    def unreachable(_token):
        raise jwt.PyJWKClientConnectionError("down")

    stub = SimpleNamespace(get_signing_key_from_jwt=unknown_kid)
    monkeypatch.setattr(security, "_jwks", stub)
    assert (await client.get("/api/v1/users/me", headers=bearer(make_token()))).status_code == 401
    stub.get_signing_key_from_jwt = unreachable
    assert (await client.get("/api/v1/users/me", headers=bearer(make_token()))).status_code == 503


@pytest.mark.parametrize("access", ["admin", ["admin", 3], None])
async def test_malformed_realm_access_does_not_crash(client, make_token, access):
    token = make_token(realm_access=access)
    r = await client.get("/api/v1/users/me", headers=bearer(token))
    assert r.status_code == 200
    assert r.json()["roles"] == []
