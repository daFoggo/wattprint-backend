import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

QUALITY_MAX = 32767  # energy.reading.quality is a smallint bit field, never negative


class MeterNotFound(LookupError):  # noqa: N818 - name fixed by the task contract
    """No core.meter row has the given serial."""


@dataclass
class ReadingRow:
    ts: datetime
    channel: str
    value: float
    quality: int = 0


@dataclass
class IngestResult:
    batch_id: UUID
    rows_in: int
    rows_new: int
    rows_dup: int
    rows_bad: int


async def _asyncpg(session: AsyncSession):
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    return raw.driver_connection


def _aware(ts: datetime) -> bool:
    return ts.tzinfo is not None and ts.utcoffset() is not None


async def _stage(session: AsyncSession, columns_sql: str, names: list[str], records) -> str:
    """COPY records into a fresh ON COMMIT DROP temp table and return its name."""
    name = f"stage_{uuid.uuid4().hex}"
    await session.execute(text(f"CREATE TEMP TABLE {name} ({columns_sql}) ON COMMIT DROP"))
    pg = await _asyncpg(session)
    await pg.copy_records_to_table(name, records=records, columns=names, schema_name="pg_temp")
    return name


async def _write_readings(session: AsyncSession, valid: list[tuple], source: str) -> int:
    """Stage the valid (series_id, ts, value, quality) rows and insert; returns rows_new."""
    if not valid:
        return 0
    stage = await _stage(
        session,
        "series_id integer, ts timestamptz, value double precision, quality smallint",
        ["series_id", "ts", "value", "quality"],
        valid,
    )
    new = await session.scalar(
        text(
            "WITH ins AS (INSERT INTO energy.reading (ts, series_id, value, quality) "
            f"SELECT ts, series_id, value::real, quality FROM {stage} ORDER BY series_id, ts "
            "ON CONFLICT (series_id, ts) DO NOTHING RETURNING 1) SELECT count(*) FROM ins"
        )
    )
    await session.execute(
        text(
            "INSERT INTO ops.ingest_checkpoint (source, series_id, last_ts) "
            f"SELECT :src, series_id, max(ts) FROM {stage} GROUP BY series_id "
            "ON CONFLICT (source, series_id) DO UPDATE SET "
            "last_ts = GREATEST(ops.ingest_checkpoint.last_ts, EXCLUDED.last_ts), "
            "updated_at = now()"
        ),
        {"src": source},
    )
    await session.execute(text(f"DROP TABLE {stage}"))
    return new


async def ingest_readings(
    session: AsyncSession, meter_serial: str, rows: Sequence[ReadingRow], source: str
) -> IngestResult:
    """Bulk-ingest meter readings; flushes but never commits (the caller commits).

    A row is bad (counted, not written) when its channel is not mapped to a series of the meter,
    its value is NaN/inf, its ts is naive, or its quality is outside 0..32767. A row is a
    duplicate when (series_id, ts) is already stored or repeats earlier in the same batch; the
    first occurrence in the batch is the one stored. rows_in == rows_new + rows_dup + rows_bad.
    The ingest_batch row survives a failed write (marked 'failed' with the error as note) while
    the data write itself is rolled back through a savepoint, and the error is re-raised.
    """
    meter = (
        await session.execute(
            text("SELECT id, home_id FROM core.meter WHERE serial = :s"), {"s": meter_serial}
        )
    ).first()
    if meter is None:
        raise MeterNotFound(f"meter {meter_serial!r} not found")
    channels = dict(
        (
            await session.execute(
                text(
                    "SELECT source_channel, series_id FROM energy.series "
                    "WHERE meter_id = :m AND source_channel IS NOT NULL"
                ),
                {"m": meter.id},
            )
        ).all()
    )

    bad = 0
    seen: set[tuple[int, datetime]] = set()
    valid: list[tuple] = []
    dup = 0
    for r in rows:
        sid = channels.get(r.channel)
        try:
            value = float(r.value)
            ok = (
                sid is not None
                and _aware(r.ts)
                and math.isfinite(value)
                and isinstance(r.quality, int)
                and 0 <= r.quality <= QUALITY_MAX
            )
        except (TypeError, ValueError, OverflowError):
            ok = False
        if not ok:
            bad += 1
            continue
        key = (sid, r.ts)
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        valid.append((sid, r.ts, value, r.quality))

    batch_id = await session.scalar(
        text(
            "INSERT INTO ops.ingest_batch (source, home_id, status) "
            "VALUES (:src, :h, 'running') RETURNING id"
        ),
        {"src": source, "h": meter.home_id},
    )
    try:
        async with session.begin_nested():
            new = await _write_readings(session, valid, source)
    except Exception as exc:
        await session.execute(
            text(
                "UPDATE ops.ingest_batch SET status = 'failed', finished_at = now(), "
                "note = :n WHERE id = :i"
            ),
            {"n": f"{type(exc).__name__}: {exc}"[:2000], "i": batch_id},
        )
        await session.flush()
        raise

    dup += len(valid) - new  # already stored
    await session.execute(
        text(
            "UPDATE ops.ingest_batch SET status = 'ok', finished_at = now(), rows_in = :i, "
            "rows_new = :n, rows_dup = :d, rows_bad = :b WHERE id = :id"
        ),
        {"i": len(rows), "n": new, "d": dup, "b": bad, "id": batch_id},
    )
    await session.flush()
    return IngestResult(batch_id, len(rows), new, dup, bad)


async def ingest_estimates(
    session: AsyncSession, run_id: int, rows: Sequence[tuple[datetime, int, float]]
) -> int:
    """Upsert device estimates (ts, series_id, value); the latest run wins. Returns rows written.

    Non-finite values are skipped; a repeated (series_id, ts) inside the call keeps the last
    value. A naive ts raises ValueError. Flushes but never commits.
    """
    latest: dict[tuple[int, datetime], float] = {}
    for ts, series_id, value in rows:
        if not _aware(ts):
            raise ValueError("estimate ts must be timezone-aware")
        value = float(value)
        if math.isfinite(value):
            latest[(series_id, ts)] = value
    if not latest:
        return 0
    records = [(sid, ts, v, run_id) for (sid, ts), v in latest.items()]
    stage = await _stage(
        session,
        "series_id integer, ts timestamptz, value double precision, run_id integer",
        ["series_id", "ts", "value", "run_id"],
        records,
    )
    written = await session.scalar(
        text(
            "WITH up AS (INSERT INTO energy.device_estimate (ts, series_id, value, run_id) "
            f"SELECT ts, series_id, value::real, run_id FROM {stage} ORDER BY series_id, ts "
            "ON CONFLICT (series_id, ts) DO UPDATE SET value = EXCLUDED.value, "
            "run_id = EXCLUDED.run_id RETURNING 1) SELECT count(*) FROM up"
        )
    )
    await session.execute(text(f"DROP TABLE {stage}"))
    await session.flush()
    return written
