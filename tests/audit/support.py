"""Shared plumbing of the audit: database creation, engines."""

import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from tests.db.conftest import run_alembic

ADMIN_URL_ENV = "AUDIT_ADMIN_URL"


AUDIT_DB_PREFIX = "wattprint_audit"


class NotAuditTarget(RuntimeError):  # noqa: N818 - reads better as a refusal
    """The audit would run against a database that is not the isolated audit database."""


def check_target(database_url: str, admin_url: str | None) -> str:
    """Refuse unless DATABASE_URL names a `wattprint_audit*` database and AUDIT_ADMIN_URL is set.

    The audit loads hundreds of millions of rows, switches policies off, compresses chunks and
    (in 10b) drops databases: it must never run against the shared development database.
    """
    name = make_url(database_url).database or ""
    if not name.startswith(AUDIT_DB_PREFIX):
        raise NotAuditTarget(
            f"refusing to run the audit on database {name!r}: its name must start with "
            f"{AUDIT_DB_PREFIX!r} (use .superpowers/sdd/.../run-audit.sh)"
        )
    if not admin_url:
        raise NotAuditTarget(f"refusing to run the audit: {ADMIN_URL_ENV} is not set")
    return name


def guard() -> str:
    return check_target(settings.database_url, os.environ.get(ADMIN_URL_ENV))


def database_name() -> str:
    return make_url(settings.database_url).database


async def ensure_database() -> str:
    """Create the audit database if missing and migrate it to head. Returns its DSN."""
    guard()
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
                await c.execute(text("SELECT public.set_policies(false)"))
        finally:
            await eng.dispose()
    return dsn


def make_engine(**kw):
    guard()
    return create_async_engine(settings.database_url, **kw)


def scratch_url(name: str) -> str:
    """URL of a scratch database next to the audit database (never the audit database itself)."""
    guard()
    if not name.startswith(AUDIT_DB_PREFIX + "_") or name == database_name():
        raise NotAuditTarget(f"scratch database name must be {AUDIT_DB_PREFIX}_<suffix>: {name!r}")
    return make_url(settings.database_url).set(database=name).render_as_string(hide_password=False)


async def create_scratch(name: str, migrate: bool = True, policies_off: bool = True) -> str:
    """Drop and recreate a scratch database on the audit server; migrate it to head."""
    dsn = scratch_url(name)
    await drop_scratch(name)
    admin = create_async_engine(os.environ[ADMIN_URL_ENV], isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            await c.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()
    if migrate:
        run_alembic(dsn, "upgrade", "head")
        if policies_off:
            eng = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
            try:
                async with eng.connect() as c:
                    await c.execute(text("SELECT public.set_policies(false)"))
            finally:
                await eng.dispose()
    return dsn


async def drop_scratch(name: str) -> None:
    scratch_url(name)  # validates the name
    admin = create_async_engine(os.environ[ADMIN_URL_ENV], isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await admin.dispose()
