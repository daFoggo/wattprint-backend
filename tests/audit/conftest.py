import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.audit.support import ensure_database, make_engine


@pytest.fixture(scope="session", autouse=True)
async def audit_db():
    return await ensure_database()


@pytest.fixture(scope="session")
async def engine(audit_db):
    eng = make_engine(pool_pre_ping=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
async def conn(engine):
    async with engine.connect() as c:
        await c.execute(text("SET work_mem = '256MB'"))
        yield c
