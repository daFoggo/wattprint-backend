"""The two connections of a run: the scope token on the app session, read-only Copilot SQL."""

import datetime as dt
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ScopeToken
from ...services.ingest import _asyncpg

COPILOT_ROLE = "wattprint_copilot_ro"


class QueryFailedError(RuntimeError):
    """A generated query failed in the database; its message goes to the repair loop."""


async def issue_scope_token(session: AsyncSession, home_id: uuid.UUID | str) -> str:
    """Prune this home's expired tokens, insert a new one (5 minutes), commit."""
    await session.execute(
        delete(ScopeToken).where(ScopeToken.home_id == home_id, ScopeToken.expires_at <= func.now())
    )
    token = await session.scalar(
        insert(ScopeToken).values(home_id=home_id).returning(ScopeToken.token)
    )
    await session.commit()
    return str(token)


@asynccontextmanager
async def copilot_tx(sessions, token: str) -> AsyncIterator[Any]:
    """A read-only transaction on the Copilot login, scoped to the token's home.

    Yields the raw asyncpg connection (positional $n parameters). In the API the sessions are the
    Copilot login (database.copilot_sessions refuses any other user), where SET LOCAL ROLE is a
    no-op; it is a second fence that also lets tests use a scratch superuser. statement_timeout is
    set here because a role's setting applies only at login. Always rolled back.
    """
    async with sessions() as session:
        try:
            # through the session: it opens the transaction (asyncpg's starts lazily), so the
            # SET LOCALs and the transaction-local token below really are inside it
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text(f"SET LOCAL ROLE {COPILOT_ROLE}"))
            await session.execute(text("SET LOCAL statement_timeout = '5s'"))
            await session.execute(
                text("SELECT set_config('app.copilot_token', :t, true)"), {"t": token}
            )
            yield await _asyncpg(session)
        finally:
            await session.rollback()


def plain(value: Any) -> Any:
    """A database value as JSON-friendly state (the graph state is checkpointed)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


async def run(conn, sql: str, params: list[Any]) -> tuple[list[str], list[dict[str, Any]], int]:
    """(columns, rows, duration ms). A database error becomes QueryFailedError."""
    started = time.perf_counter()
    try:
        stmt = await conn.prepare(sql)
        records = await stmt.fetch(*params)
    except Exception as exc:  # asyncpg errors carry the server message
        raise QueryFailedError(f"{type(exc).__name__}: {exc}"[:500]) from exc
    columns = [a.name for a in stmt.get_attributes()]
    rows = [{k: plain(v) for k, v in r.items()} for r in records]
    return columns, rows, int((time.perf_counter() - started) * 1000)
