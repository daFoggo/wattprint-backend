import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

SCHEMAS = {"core", "catalog", "energy", "billing", "insight", "copilot", "knowledge", "ops"}
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


async def test_roles_exist_nologin_without_password(conn):
    rows = await conn.execute(
        text("SELECT rolname, rolcanlogin, rolconfig FROM pg_roles WHERE rolname = ANY(:n)"),
        {"n": list(ROLES)},
    )
    found = {r[0]: r for r in rows}
    assert set(found) == set(ROLES)
    # The scratch migration runs without *_DB_PASSWORD env vars.
    assert not any(r[1] for r in found.values())
    assert "statement_timeout=5s" in found["wattprint_copilot_ro"][2]


async def test_ingest_role_cannot_create_table(conn):
    await conn.execute(text("SET LOCAL ROLE wattprint_ingest"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        await conn.execute(text("CREATE TABLE energy.should_fail (id int)"))
