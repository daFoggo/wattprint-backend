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


@pytest.fixture(scope="session")
async def scratch_dsn():
    base = make_url(settings.database_url)
    name = f"wattprint_test_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'CREATE DATABASE "{name}"'))
    dsn = base.set(database=name).render_as_string(hide_password=False)
    try:
        env = {k: v for k, v in os.environ.items() if not k.endswith("_DB_PASSWORD")}
        env["DATABASE_URL"] = dsn
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"alembic upgrade failed:\n{proc.stdout}\n{proc.stderr}")
        yield dsn
    finally:
        async with admin.connect() as c:
            await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest.fixture(scope="session")
async def scratch_engine(scratch_dsn):
    engine = create_async_engine(scratch_dsn)
    yield engine
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
    async with engine.connect() as c:
        yield c
    await engine.dispose()
