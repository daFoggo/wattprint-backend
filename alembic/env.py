# Revisions are hand-written; do not use --autogenerate (hypertables and continuous aggregates are not in the metadata).  # noqa: E501
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app import models  # noqa: F401
from app.config import settings
from app.database import Base

target_metadata = Base.metadata


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
