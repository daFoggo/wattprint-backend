import asyncio
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from app.database import SessionLocal
from app.models import RefreshToken
from app.security import hash_token
from tests._helpers import PASSWORD


async def _register_and_login(client: AsyncClient, email: str) -> dict:
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201
    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200
    return r.json()


async def test_openapi_exposes_password_flow(client):
    spec = (await client.get("/openapi.json")).json()
    flows = spec["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]
    assert flows["password"]["tokenUrl"] == "api/v1/auth/token"


async def test_me_requires_token(client):
    r = await client.get("/api/v1/users/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_register_login_me(client, email):
    tokens = await _register_and_login(client, email)
    assert tokens["token_type"] == "bearer"
    r = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 200
    assert r.json()["email"] == email
    assert "hashed_password" not in r.json()


async def test_duplicate_email_conflicts(client, email):
    await _register_and_login(client, email)
    r = await client.post(
        "/api/v1/auth/register", json={"email": email.upper(), "password": PASSWORD}
    )
    assert r.status_code == 409


async def test_wrong_password_rejected(client, email):
    await _register_and_login(client, email)
    r = await client.post("/api/v1/auth/token", data={"username": email, "password": "nope-nope"})
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/token", data={"username": "ghost@example.com", "password": PASSWORD}
    )
    assert r.status_code == 401


async def test_garbage_token_rejected(client):
    r = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_refresh_rotates_and_detects_reuse(client, email):
    first = await _register_and_login(client, email)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]

    # Replaying the already-used token fails and revokes the whole chain.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401


async def test_logout_revokes_refresh_token(client, email):
    tokens = await _register_and_login(client, email)
    r = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


async def test_concurrent_refresh_only_one_wins(client, email):
    tokens = await _register_and_login(client, email)
    body = {"refresh_token": tokens["refresh_token"]}
    results = await asyncio.gather(
        client.post("/api/v1/auth/refresh", json=body),
        client.post("/api/v1/auth/refresh", json=body),
    )
    assert sorted(r.status_code for r in results) == [200, 401]


async def test_expired_refresh_token_rejected(client, email):
    tokens = await _register_and_login(client, email)
    async with SessionLocal() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(tokens["refresh_token"]))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401
