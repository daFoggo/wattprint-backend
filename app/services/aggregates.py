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

    Use it to pick up late rows older than the policy start_offset. The window is widened per
    view to whole buckets. `conn` must be in AUTOCOMMIT mode: refresh_continuous_aggregate()
    cannot run inside a transaction block or a function, which is why this is not an SQL
    procedure.
    """
    for view, step in AGGREGATES:
        start = _snap(from_ts, step)[0]
        end = _snap(to_ts, step)[1]
        await conn.execute(
            text("CALL refresh_continuous_aggregate(CAST(:v AS regclass), "
                 "CAST(:f AS timestamptz), CAST(:t AS timestamptz))"),
            {"v": view, "f": start, "t": end},
        )
