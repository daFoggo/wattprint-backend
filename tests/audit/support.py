"""Shared plumbing of the audit: database creation, engines."""

import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from tests.db.conftest import run_alembic

ADMIN_URL_ENV = "AUDIT_ADMIN_URL"


def database_name() -> str:
    return make_url(settings.database_url).database


async def ensure_database() -> str:
    """Create the audit database if missing and migrate it to head. Returns its DSN."""
    dsn = settings.database_url
    name = database_name()
    admin_url = os.environ.get(ADMIN_URL_ENV) or make_url(dsn).set(database="postgres")
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            exists = await c.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            )
            if not exists:
                await c.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()
    # The first migration run turns policies ON (migration c8a4e1f7b295); a brand-new audit
    # database is switched off at once so no job touches the load. Upgrading again is a no-op.
    run_alembic(dsn, "upgrade", "head")
    if not exists:
        eng = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
        try:
            async with eng.connect() as c:
                await c.execute(text("SELECT ops.set_policies(false)"))
        finally:
            await eng.dispose()
    return dsn


def make_engine(**kw):
    return create_async_engine(settings.database_url, **kw)
