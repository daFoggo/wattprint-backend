import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.db.conftest import load_revision, run_alembic

foundation = load_revision("20261101_5f0b3c8a1d47")

SCHEMAS = {"public", "copilot_ro"}
ROLES = ("wattprint_app", "wattprint_ingest", "wattprint_copilot_ro")


async def test_extension_versions(conn):
    rows = await conn.execute(text("SELECT extname, extversion FROM pg_extension"))
    ext = dict(rows.all())
    assert ext["timescaledb"] == "2.31.0"
    assert ext["vector"] == "0.8.1"
    assert "unaccent" in ext
    assert "pg_trgm" in ext


async def test_schemas_exist(conn):
    rows = await conn.execute(text("SELECT nspname FROM pg_namespace"))
    assert SCHEMAS <= {r[0] for r in rows}


async def test_roles_exist_with_copilot_timeout(conn):
    # Login state depends on the developer's *_DB_PASSWORD env, so it is not asserted here.
    rows = await conn.execute(
        text("SELECT rolname, rolconfig FROM pg_roles WHERE rolname = ANY(:n)"),
        {"n": list(ROLES)},
    )
    found = dict(rows.all())
    assert set(found) == set(ROLES)
    assert "statement_timeout=5s" in found["wattprint_copilot_ro"]


async def test_ingest_role_cannot_create_table(conn):
    await conn.execute(text("SET LOCAL ROLE wattprint_ingest"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        await conn.execute(text("CREATE TABLE public.should_fail (id int)"))


def _ensure(conn, name, password):
    def run(sync_conn):
        foundation.ensure_role(lambda sql: sync_conn.execute(text(sql)), name, password)

    return conn.run_sync(run)


async def _login(conn, name):
    r = await conn.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = :n"), {"n": name})
    return r.scalar_one()


# Role DDL is transactional: the `conn` fixture rolls these throwaway roles back, so the real
# cluster roles are never touched.
async def test_new_role_without_password_is_nologin(conn):
    name = f"wt_throwaway_{uuid.uuid4().hex[:8]}"
    await _ensure(conn, name, "")
    assert await _login(conn, name) is False


async def test_existing_login_role_not_demoted_without_password(conn):
    name = f"wt_throwaway_{uuid.uuid4().hex[:8]}"
    await _ensure(conn, name, "throwaway-pw")
    assert await _login(conn, name) is True
    await _ensure(conn, name, "")
    assert await _login(conn, name) is True


async def test_downgrade_upgrade_leaves_roles_intact(throwaway_dsn):
    admin = create_async_engine(throwaway_dsn, isolation_level="AUTOCOMMIT")
    query = text(
        "SELECT r.rolname, r.rolcanlogin, a.rolpassword IS NOT NULL, r.rolconfig "
        "FROM pg_roles r JOIN pg_authid a ON a.oid = r.oid "
        "WHERE r.rolname = ANY(:n) ORDER BY r.rolname"
    )
    try:
        async with admin.connect() as c:
            before = (await c.execute(query, {"n": list(ROLES)})).all()
        assert len(before) == 3
        run_alembic(throwaway_dsn, "downgrade", "d4f6b8c0e2a1")  # undo modules and foundation
        async with admin.connect() as c:
            assert (await c.execute(query, {"n": list(ROLES)})).all() == before
        run_alembic(throwaway_dsn, "upgrade", "head")
        async with admin.connect() as c:
            assert (await c.execute(query, {"n": list(ROLES)})).all() == before
    finally:
        await admin.dispose()
