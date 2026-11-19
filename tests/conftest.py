import asyncio
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

# Tests that go through the app's own engine (API tests) must never write to the dev database:
# point the settings at "<db>_test" (or TEST_DATABASE_URL) before app.database builds its engine.
_dev = make_url(settings.database_url)
settings.database_url = os.environ.get("TEST_DATABASE_URL") or _dev.set(
    database=f"{_dev.database}_test"
).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = settings.database_url  # alembic subprocesses read it

from app.main import app  # noqa: E402
from app.modules.auth.services import token as security  # noqa: E402


async def _ensure_test_database() -> None:
    url = make_url(settings.database_url)
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            exists = await c.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            )
            if not exists:
                await c.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin.dispose()


def pytest_configure(config):
    asyncio.run(_ensure_test_database())
    env = {k: v for k, v in os.environ.items() if not k.endswith("_DB_PASSWORD")}
    env["SEED_REFIT"] = "0"
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"migrating the test database failed:\n{proc.stdout}\n{proc.stderr}")


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
            "sub": str(uuid.uuid4()) if sub is None else sub,
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


@pytest.fixture
async def make_member(client, make_token):
    """Factory: a signed-in user who is `role` of a home (a new one, or `home_id`); cleaned up."""
    from app.database import SessionLocal

    homes: list = []

    async def make(role: str = "owner", home_id=None, **home_cols):
        token = make_token(sub=str(uuid.uuid4()))
        me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        async with SessionLocal() as s, s.begin():
            if home_id is None:
                cols = {"name": "Test home", **home_cols}
                home_id = await s.scalar(
                    text(
                        f"INSERT INTO public.tb_home ({', '.join(cols)}) "
                        f"VALUES ({', '.join(':' + k for k in cols)}) RETURNING id"
                    ),
                    cols,
                )
                homes.append(home_id)
            await s.execute(
                text(
                    "INSERT INTO public.tb_home_member (home_id, user_id, role) VALUES (:h, :u, :r)"
                ),
                {"h": home_id, "u": me.json()["id"], "r": role},
            )
        return SimpleNamespace(
            token=token,
            headers={"Authorization": f"Bearer {token}"},
            user_id=uuid.UUID(me.json()["id"]),
            home_id=home_id,
        )

    yield make
    async with SessionLocal() as s, s.begin():
        for h in homes:
            await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": h})
