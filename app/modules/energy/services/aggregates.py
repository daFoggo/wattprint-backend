import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Dependency order: each hierarchical view reads the one before it. The step is the bucket width;
# the daily buckets are cut at 17:00 UTC (local midnight, Asia/Ho_Chi_Minh).
AGGREGATES = tuple(
    (f"public.{family}_{res}", step)
    for family in ("reading", "device_estimate")
    for res, step in (
        ("1m", timedelta(minutes=1)),
        ("1h", timedelta(hours=1)),
        ("1d", timedelta(days=1)),
    )
)
_DAY_ORIGIN = datetime(2000, 1, 1, 17, tzinfo=UTC)
_DAY = timedelta(days=1)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkippedWindow:
    """A view window backfill_aggregates did not refresh because its raw rows are gone."""

    view: str
    from_ts: datetime
    to_ts: datetime
    reason: str


SKIP_REASON = "materialized rows exceed the raw rows left (retention or a lone old chunk)"


def _snap(ts: datetime, step: timedelta) -> tuple[datetime, datetime]:
    """Bucket boundaries (floor, ceil) around ts: a refresh window must hold whole buckets."""
    n = (ts - _DAY_ORIGIN) / step
    return _DAY_ORIGIN + math.floor(n) * step, _DAY_ORIGIN + math.ceil(n) * step


async def _raw_row_counts(
    conn: AsyncConnection, family: str, lo: datetime, hi: datetime
) -> dict[tuple[datetime, uuid.UUID], int]:
    """Aggregated raw rows per (local day, series): the rows the aggregates are built from
    (readings: quality bit 1 clear, estimates: all)."""
    good = " FILTER (WHERE quality & 1 = 0)" if family == "reading" else ""
    res = await conn.execute(
        text(
            "SELECT time_bucket('1 day', ts, origin => CAST(:o AS timestamptz)) AS d, series_id, "
            f"count(*){good} AS n FROM public.tb_{family} WHERE ts >= :lo AND ts < :hi "
            "GROUP BY 1, 2"
        ),
        {"o": _DAY_ORIGIN, "lo": lo, "hi": hi},
    )
    return {(r.d, r.series_id): int(r.n) for r in res}


async def _materialized_row_counts(
    conn: AsyncConnection, view: str, lo: datetime, hi: datetime
) -> dict[tuple[datetime, uuid.UUID], int]:
    """`n` (rows aggregated) already MATERIALIZED in the view, per (local day, series), for
    series that still exist (rows of deleted series are orphans a refresh cannot hurt). The
    real-time part is excluded: it is computed from raw and a refresh does not destroy it."""
    schema, name = view.split(".")
    mat = (
        await conn.execute(
            text(
                "SELECT materialization_hypertable_schema AS s, "
                "materialization_hypertable_name AS n "
                "FROM timescaledb_information.continuous_aggregates "
                "WHERE view_schema = :s AND view_name = :n"
            ),
            {"s": schema, "n": name},
        )
    ).one()
    res = await conn.execute(
        text(
            "SELECT time_bucket('1 day', bucket, origin => CAST(:o AS timestamptz)) AS d, "
            f'series_id, sum(n) AS n FROM "{mat.s}"."{mat.n}" '
            "WHERE bucket >= :lo AND bucket < :hi "
            "AND series_id IN (SELECT series_id FROM public.tb_series) GROUP BY 1, 2"
        ),
        {"o": _DAY_ORIGIN, "lo": lo, "hi": hi},
    )
    return {(r.d, r.series_id): int(r.n) for r in res}


def _split(
    start: datetime, end: datetime, unsafe_days: list[datetime]
) -> tuple[list[tuple[datetime, datetime]], list[tuple[datetime, datetime]]]:
    """Cut [start, end) into (refreshable pieces, skipped pieces) around the unsafe local days.
    Day boundaries are multiples of every bucket step, so every piece holds whole buckets."""
    runs: list[list[datetime]] = []
    for d in sorted(unsafe_days):
        if runs and runs[-1][1] == d:
            runs[-1][1] = d + _DAY
        else:
            runs.append([d, d + _DAY])
    skipped, refresh, cursor = [], [], start
    for a, b in runs:
        a, b = max(a, start), min(b, end)
        if a >= b:
            continue
        if cursor < a:
            refresh.append((cursor, a))
        skipped.append((a, b))
        cursor = b
    if cursor < end:
        refresh.append((cursor, end))
    return refresh, skipped


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

    Safe by default. A refresh recomputes buckets from the raw rows that are left, so over a range
    whose raw chunks were dropped by retention (or only partly exist again, e.g. a lone misdated
    row that recreated an old chunk) it DELETES or shrinks the existing buckets. The guard works on
    row counts per series and local day (17:00 UTC cut, a boundary of every bucket step): raw rows
    are never deleted except by retention, so a day on which some existing series has a
    MATERIALIZED `n` above its aggregated raw rows still present is unsafe, and exactly those
    days are not refreshed (the rest of the window is). They are returned, merged into
    runs per view, as SkippedWindow and logged as warnings.
    A fresh history (nothing materialized yet) and late rows (raw >= materialized) are refreshed as
    usual. The check scans the raw rows of the window once per family: backfilling is an admin
    operation, not a hot path. Known limit: the guard compares materialized `n` with the raw rows
    still present per series and local day, so on a partly dropped local day an equal or higher
    raw count produced by late rows of the same series hides the loss; passing the guard does not
    prove the raw rows are intact. Pass allow_missing_raw=True only to rebuild from scratch, when
    emptying or shrinking the aggregates of a range is intended; raw rows deliberately flagged
    or removed after being aggregated need that opt-in too.
    """
    if from_ts.tzinfo is None or to_ts.tzinfo is None:
        raise ValueError("from_ts and to_ts must be timezone-aware datetimes")
    # The asyncpg adapter exposes AUTOCOMMIT (engine- or execution-option level) as this flag;
    # get_isolation_level() only reports the server-side level.
    if conn.sync_connection.connection.dbapi_connection.isolation_level != "autocommit":
        raise RuntimeError("backfill_aggregates needs an AUTOCOMMIT connection")
    now = datetime.now(UTC)
    day_lo, day_hi = _snap(from_ts, _DAY)[0], _snap(to_ts, _DAY)[1]
    raw: dict[str, dict[tuple[datetime, uuid.UUID], int]] = {}
    skipped: list[SkippedWindow] = []
    for view, step in AGGREGATES:
        start = _snap(from_ts, step)[0]
        end = min(_snap(to_ts, step)[1], _snap(now, step)[0])
        if start >= end:
            continue
        pieces = [(start, end)]
        if not allow_missing_raw:
            family = view.split(".")[1].rsplit("_", 1)[0]
            if family not in raw:
                raw[family] = await _raw_row_counts(conn, family, day_lo, day_hi)
            materialized = await _materialized_row_counts(conn, view, day_lo, day_hi)
            unsafe = {d for (d, sid), n in materialized.items() if n > raw[family].get((d, sid), 0)}
            pieces, bad = _split(start, end, sorted(unsafe))
            skipped += [SkippedWindow(view, a, b, SKIP_REASON) for a, b in bad]
        for a, b in pieces:
            await conn.execute(
                text(
                    "CALL refresh_continuous_aggregate(CAST(:v AS regclass), "
                    "CAST(:f AS timestamptz), CAST(:t AS timestamptz))"
                ),
                {"v": view, "f": a, "t": b},
            )
    for w in skipped:
        log.warning("backfill skipped %s [%s, %s): %s", w.view, w.from_ts, w.to_ts, w.reason)
    return skipped
