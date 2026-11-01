from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import update

from app.config import settings
from app.database import SessionLocal
from app.models import User
from tests._helpers import PASSWORD


def _token(sub: str, key: str, exp_delta: timedelta = timedelta(minutes=5)) -> str:
    now = datetime.now(UTC)
    claims = {"sub": sub, "iat": now, "exp": now + exp_delta}
    return jwt.encode(claims, key, algorithm=settings.jwt_algorithm)


async def _me(client: AsyncClient, token: str):
    return await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})


async def _real_user(client: AsyncClient, email: str) -> tuple[str, str]:
    """Register + log in; return (user id, issued access token)."""
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201
    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200
    access = r.json()["access_token"]
    return jwt.decode(access, options={"verify_signature": False})["sub"], access


async def test_token_signed_with_other_key_rejected(client, email):
    user_id, _ = await _real_user(client, email)
    # Control: same claims, real key -> accepted, so the 401 below is due to the key.
    assert (await _me(client, _token(user_id, settings.jwt_secret_key))).status_code == 200
    assert (await _me(client, _token(user_id, "x" * 32))).status_code == 401


async def test_expired_access_token_rejected(client, email):
    user_id, _ = await _real_user(client, email)
    assert (await _me(client, _token(user_id, settings.jwt_secret_key))).status_code == 200
    expired = _token(user_id, settings.jwt_secret_key, timedelta(minutes=-5))
    assert (await _me(client, expired)).status_code == 401


async def test_non_uuid_sub_rejected(client):
    r = await _me(client, _token("not-a-uuid", settings.jwt_secret_key))
    assert r.status_code == 401


async def test_inactive_user_cannot_login_or_use_token(client, email):
    _, access = await _real_user(client, email)

    async with SessionLocal() as session:
        await session.execute(update(User).where(User.email == email).values(is_active=False))
        await session.commit()

    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 400
    assert (await _me(client, access)).status_code == 400
