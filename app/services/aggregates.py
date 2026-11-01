import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Dependency order: each hierarchical view reads the one before it. The step is the bucket width;
# the daily buckets are cut at 17:00 UTC (local midnight, Asia/Ho_Chi_Minh).
AGGREGATES = tuple(
    (f"energy.{family}_{res}", step)
    for family in ("reading", "device_estimate")
    for res, step in (
        ("1m", timedelta(minutes=1)),
        ("1h", timedelta(hours=1)),
        ("1d", timedelta(days=1)),
    )
)
_DAY_ORIGIN = datetime(2000, 1, 1, 17, tzinfo=UTC)


def _snap(ts: datetime, step: timedelta) -> tuple[datetime, datetime]:
    """Bucket boundaries (floor, ceil) around ts: a refresh window must hold whole buckets."""
    n = (ts - _DAY_ORIGIN) / step
    return _DAY_ORIGIN + math.floor(n) * step, _DAY_ORIGIN + math.ceil(n) * step


async def backfill_aggregates(
    conn: AsyncConnection, from_ts: datetime, to_ts: datetime
) -> None:
    """Refresh the six continuous aggregates over [from_ts, to_ts) in dependency order.

    Use it to pick up late rows older than the policy start_offset. Per view the window is
    widened to whole buckets at the start and ends at the last CLOSED bucket (never later than
    now), so the open current bucket is never materialized: it stays served by real-time
    aggregation and the watermark does not move past now. A view whose window is empty is
    skipped. `conn` must be in AUTOCOMMIT mode: refresh_continuous_aggregate() cannot run inside
    a transaction block or a function, which is why this is not an SQL procedure.
    """
    if from_ts.tzinfo is None or to_ts.tzinfo is None:
        raise ValueError("from_ts and to_ts must be timezone-aware datetimes")
    # The asyncpg adapter exposes AUTOCOMMIT (engine- or execution-option level) as this flag;
    # get_isolation_level() only reports the server-side level.
    if conn.sync_connection.connection.dbapi_connection.isolation_level != "autocommit":
        raise RuntimeError("backfill_aggregates needs an AUTOCOMMIT connection")
    now = datetime.now(UTC)
    for view, step in AGGREGATES:
        start = _snap(from_ts, step)[0]
        end = min(_snap(to_ts, step)[1], _snap(now, step)[0])
        if start >= end:
            continue
        await conn.execute(
            text("CALL refresh_continuous_aggregate(CAST(:v AS regclass), "
                 "CAST(:f AS timestamptz), CAST(:t AS timestamptz))"),
            {"v": view, "f": start, "t": end},
        )
