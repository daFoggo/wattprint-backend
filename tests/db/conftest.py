import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings

ROOT = Path(__file__).resolve().parents[2]


def run_alembic(dsn: str, *args: str, **extra_env: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.endswith("_DB_PASSWORD")}
    env["SEED_REFIT"] = "0"  # skip the REFIT seed revision: tests start from an empty database
    env.update(extra_env)
    env["DATABASE_URL"] = dsn
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        cmd = " ".join(args)
        raise RuntimeError(f"alembic {cmd} failed:\n{proc.stdout}\n{proc.stderr}")


def load_revision(prefix: str):
    """Import an Alembic revision module by file prefix (file names are not importable)."""
    path = next((ROOT / "alembic" / "versions").glob(f"{prefix}*.py"))
    spec = importlib.util.spec_from_file_location(f"rev_{prefix}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _create_migrated_db():
    """Create a scratch database and migrate it. Returns (dsn, drop coroutine function)."""
    base = make_url(settings.database_url)
    name = f"wattprint_test_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'CREATE DATABASE "{name}"'))

    async def drop():
        try:
            async with admin.connect() as c:
                await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        finally:
            await admin.dispose()

    dsn = base.set(database=name).render_as_string(hide_password=False)
    try:
        run_alembic(dsn, "upgrade", "head")
    except BaseException:
        await drop()
        raise
    return dsn, drop


RELATIONS = text(
    "SELECT table_schema || '.' || table_name FROM information_schema.tables "
    "WHERE table_schema IN ('public', 'ai', 'copilot_ro')"
)


async def relations(conn) -> set[str]:
    """Tables and views across the app schemas: a downgrade test checks which ones its
    revisions own, since later modules (auth, AI...) live in the same schemas."""
    return set((await conn.scalars(RELATIONS)).all())


@pytest.fixture(scope="session")
async def scratch_dsn():
    dsn, drop = await _create_migrated_db()
    try:
        yield dsn
    finally:
        await drop()


@pytest.fixture
async def throwaway_dsn():
    """A private migrated database for tests that downgrade or otherwise mutate the schema."""
    dsn, drop = await _create_migrated_db()
    try:
        yield dsn
    finally:
        await drop()


@pytest.fixture(scope="session")
async def scratch_engine(scratch_dsn):
    engine = create_async_engine(scratch_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def conn(scratch_engine):
    async with scratch_engine.connect() as c:
        trans = await c.begin()
        try:
            yield c
        finally:
            await trans.rollback()


@pytest.fixture
async def session(conn):
    async with AsyncSession(bind=conn, expire_on_commit=False) as s:
        yield s


@pytest.fixture
async def autocommit_conn(scratch_dsn):
    engine = create_async_engine(scratch_dsn, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            yield c
    finally:
        await engine.dispose()
