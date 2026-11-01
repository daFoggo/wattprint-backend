import uuid
from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import update

from app.config import settings
from app.database import get_session
from app.models import User
from tests.conftest import PASSWORD


def _token(sub: str, key: str, exp_delta: timedelta = timedelta(minutes=5)) -> str:
    now = datetime.now(UTC)
    claims = {"sub": sub, "iat": now, "exp": now + exp_delta}
    return jwt.encode(claims, key, algorithm=settings.jwt_algorithm)


async def _me(client: AsyncClient, token: str):
    return await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})


async def test_token_signed_with_other_key_rejected(client):
    r = await _me(client, _token(str(uuid.uuid4()), "x" * 32))
    assert r.status_code == 401


async def test_expired_access_token_rejected(client):
    r = await _me(
        client, _token(str(uuid.uuid4()), settings.jwt_secret_key, timedelta(minutes=-5))
    )
    assert r.status_code == 401


async def test_non_uuid_sub_rejected(client):
    r = await _me(client, _token("not-a-uuid", settings.jwt_secret_key))
    assert r.status_code == 401


async def test_inactive_user_cannot_login_or_use_token(client, email):
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201
    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200
    access = r.json()["access_token"]

    session_gen = get_session()
    session = await anext(session_gen)
    try:
        await session.execute(update(User).where(User.email == email).values(is_active=False))
        await session.commit()
    finally:
        await session_gen.aclose()

    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 400
    assert (await _me(client, access)).status_code == 400
