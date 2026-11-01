import logging
import math
from dataclasses import dataclass
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
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkippedWindow:
    """A view window backfill_aggregates did not refresh because its raw rows are gone."""

    view: str
    from_ts: datetime
    to_ts: datetime
    reason: str


def _snap(ts: datetime, step: timedelta) -> tuple[datetime, datetime]:
    """Bucket boundaries (floor, ceil) around ts: a refresh window must hold whole buckets."""
    n = (ts - _DAY_ORIGIN) / step
    return _DAY_ORIGIN + math.floor(n) * step, _DAY_ORIGIN + math.ceil(n) * step


async def _oldest_raw(conn: AsyncConnection, family: str) -> datetime | None:
    """Start of the oldest raw chunk of energy.<family>, None when it has no chunk."""
    return await conn.scalar(
        text("SELECT min(range_start) FROM timescaledb_information.chunks "
             "WHERE hypertable_schema = 'energy' AND hypertable_name = :f"),
        {"f": family},
    )


async def _has_rows(conn: AsyncConnection, view: str, lo: datetime, hi: datetime) -> bool:
    """Does the MATERIALIZED part of the view hold a bucket in [lo, hi)? (The real-time part would
    also show rows computed from raw, which a refresh does not destroy.)"""
    schema, name = view.split(".")
    mat = (
        await conn.execute(
            text("SELECT materialization_hypertable_schema AS s, "
                 "materialization_hypertable_name AS n "
                 "FROM timescaledb_information.continuous_aggregates "
                 "WHERE view_schema = :s AND view_name = :n"),
            {"s": schema, "n": name},
        )
    ).one()
    return bool(await conn.scalar(
        text(f'SELECT EXISTS (SELECT 1 FROM "{mat.s}"."{mat.n}" '
             "WHERE bucket >= :lo AND bucket < :hi)"),
        {"lo": lo, "hi": hi},
    ))


async def backfill_aggregates(
    conn: AsyncConnection,
    from_ts: datetime,
    to_ts: datetime,
    allow_missing_raw: bool = False,
) -> list[SkippedWindow]:
    """Refresh the six continuous aggregates over [from_ts, to_ts) in dependency order.

    Use it to pick up late rows older than the policy start_offset. Per view the window is
    widened to whole buckets at the start and ends at the last CLOSED bucket (never later than
    now), so the open current bucket is never materialized: it stays served by real-time
    aggregation and the watermark does not move past now. A view whose window is empty is
    skipped. `conn` must be in AUTOCOMMIT mode: refresh_continuous_aggregate() cannot run inside
    a transaction block or a function, which is why this is not an SQL procedure.

    Safe by default: a refresh over a range whose raw chunks were already dropped (retention)
    DELETES the aggregate buckets of that range, because the aggregate is recomputed from nothing.
    So where a view already holds buckets older than the oldest existing raw chunk of its family
    (reading or device_estimate), its window is clamped to start at the first whole bucket inside
    that chunk; the part before it is not refreshed and is returned (and logged) as SkippedWindow.
    A family with no raw chunk at all skips every window that holds aggregate rows. Windows
    without existing aggregate rows (a fresh history) are refreshed as usual. Pass
    allow_missing_raw=True only to rebuild from scratch, when emptying the
    aggregates of a range without raw rows is intended.
    """
    if from_ts.tzinfo is None or to_ts.tzinfo is None:
        raise ValueError("from_ts and to_ts must be timezone-aware datetimes")
    # The asyncpg adapter exposes AUTOCOMMIT (engine- or execution-option level) as this flag;
    # get_isolation_level() only reports the server-side level.
    if conn.sync_connection.connection.dbapi_connection.isolation_level != "autocommit":
        raise RuntimeError("backfill_aggregates needs an AUTOCOMMIT connection")
    now = datetime.now(UTC)
    skipped: list[SkippedWindow] = []
    oldest: dict[str, datetime | None] = {}
    for view, step in AGGREGATES:
        start = _snap(from_ts, step)[0]
        end = min(_snap(to_ts, step)[1], _snap(now, step)[0])
        if start >= end:
            continue
        if not allow_missing_raw:
            family = view.split(".")[1].rsplit("_", 1)[0]
            if family not in oldest:
                oldest[family] = await _oldest_raw(conn, family)
            first = oldest[family]
            # Only buckets that already hold aggregate rows can be destroyed. The first bucket a
            # raw chunk partly covers is skipped too (part of its raw rows may be gone); a fresh
            # history whose first bucket is not materialized yet is refreshed normally.
            limit = end if first is None else min(end, first)
            if limit > start and await _has_rows(conn, view, start, limit):
                if first is None:
                    skipped.append(SkippedWindow(view, start, end, "no raw rows for this range"))
                    continue
                floor, ceil = _snap(first, step)
                first_ok = first if floor == first else ceil
                if first_ok >= end:
                    skipped.append(
                        SkippedWindow(view, start, end, "older than the oldest raw chunk"))
                    continue
                if start < first_ok:
                    skipped.append(
                        SkippedWindow(view, start, first_ok, "older than the oldest raw chunk"))
                    start = first_ok
        await conn.execute(
            text("CALL refresh_continuous_aggregate(CAST(:v AS regclass), "
                 "CAST(:f AS timestamptz), CAST(:t AS timestamptz))"),
            {"v": view, "f": start, "t": end},
        )
    for w in skipped:
        log.warning("backfill skipped %s [%s, %s): %s", w.view, w.from_ts, w.to_ts, w.reason)
    return skipped
