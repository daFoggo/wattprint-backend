from collections.abc import AsyncIterator
from functools import cache

from sqlalchemy import MetaData
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    # Business tables live in "public".
    metadata = MetaData(naming_convention=NAMING)


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@cache
def copilot_sessions() -> async_sessionmaker[AsyncSession]:
    """Sessions on the Copilot's read-only login (settings.copilot_database_url)."""
    if not settings.copilot_database_url:
        raise RuntimeError("COPILOT_DATABASE_URL is not set: the Copilot is off")
    # docs/database-design.md: generated SQL runs on its own login, never the app's
    user = make_url(settings.copilot_database_url).username
    if user != "wattprint_copilot_ro":
        raise RuntimeError(f"COPILOT_DATABASE_URL must log in as wattprint_copilot_ro, not {user}")
    engine = create_async_engine(
        settings.copilot_database_url, pool_size=2, max_overflow=2, pool_pre_ping=True
    )
    return async_sessionmaker(engine, expire_on_commit=False)
