import asyncio
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.database import SessionLocal
from app.models import RefreshToken, User
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


async def test_refresh_rotates_and_replay_within_grace_keeps_chain(client, email):
    first = await _register_and_login(client, email)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]

    # Benign replay inside the grace window is rejected but does not kill the chain.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 200


async def test_replay_after_grace_detects_reuse_and_revokes_chain(client, email):
    first = await _register_and_login(client, email)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()

    async with SessionLocal() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(first["refresh_token"]))
            .values(revoked_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

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


async def test_issue_tokens_prunes_only_expired_tokens_of_same_user(client, email):
    now = datetime.now(UTC)
    tag = email.split("@")[0]
    tokens = await _register_and_login(client, email)
    other = await _register_and_login(client, f"other-{email}")
    async with SessionLocal() as session:
        user_id = await session.scalar(select(User.id).where(User.email == email))
        other_id = await session.scalar(select(User.id).where(User.email == f"other-{email}"))

        def row(uid, tag, expires, revoked=None):
            return RefreshToken(user_id=uid, token_hash=tag, expires_at=expires, revoked_at=revoked)

        old = now - timedelta(days=2)
        session.add_all(
            [
                row(user_id, f"stale-expired-{tag}", old),
                row(user_id, f"old-revoked-{tag}", now + timedelta(days=5), old),
                row(
                    user_id,
                    f"fresh-revoked-{tag}",
                    now + timedelta(days=5),
                    now - timedelta(hours=1),
                ),
                row(other_id, f"other-stale-{tag}", old),
            ]
        )
        await session.commit()

    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200

    async with SessionLocal() as session:
        hashes = set(await session.scalars(select(RefreshToken.token_hash)))
    assert f"stale-expired-{tag}" not in hashes  # expired rows are pruned
    assert f"old-revoked-{tag}" in hashes
    assert f"fresh-revoked-{tag}" in hashes
    assert f"other-stale-{tag}" in hashes
    assert hash_token(tokens["refresh_token"]) in hashes
    assert hash_token(other["refresh_token"]) in hashes


async def test_old_revoked_unexpired_token_survives_prune_and_replay_revokes_chain(client, email):
    first = await _register_and_login(client, email)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()

    async with SessionLocal() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(first["refresh_token"]))
            .values(revoked_at=datetime.now(UTC) - timedelta(days=2))
        )
        await session.commit()

    # A new login prunes, but must keep the old revoked (unexpired) row.
    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200
    live = r.json()

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    for tok in (second, live):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
        assert r.status_code == 401


async def test_raw_sql_insert_uses_server_defaults():
    async with SessionLocal() as session:
        await session.execute(
            text("INSERT INTO users (id, email) VALUES (gen_random_uuid(), 'raw@example.com')")
        )
        row = (
            await session.execute(
                text("SELECT is_active, created_at FROM users WHERE email = 'raw@example.com'")
            )
        ).one()
        await session.rollback()
    assert row.is_active is True
    assert row.created_at is not None
