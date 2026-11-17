import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.energy.api import backfill_aggregates
from app.modules.ops.api import ingest_estimates

from . import windows
from .devices import OTHER, ensure_devices

log = logging.getLogger(__name__)

SOURCE = "nilm"  # tb_ingest_checkpoint.source of the main series: every bin before it is final
CHUNK = timedelta(days=1)  # readings per pass while catching up
POLICY_1M = timedelta(days=6)  # older estimates are outside the 1m refresh policy (7 days)
LOCK = text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))")
UNLOCK = text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))")


@dataclass(frozen=True)
class Target:
    home_id: uuid.UUID
    timezone: str
    main_series: uuid.UUID
    model_name: str
    model_version: str
    artifact: str


@dataclass
class PassResult:
    run_id: uuid.UUID | None
    written: int
    start: datetime | None  # first bin (re)written
    reached: datetime | None  # end of the slice read
    newest: datetime | None  # newest reading when the pass began


TARGETS = text("""
    SELECT h.id AS home_id, h.timezone, s.series_id AS main_series,
           m.name AS model_name, m.version AS model_version, m.artifact
    FROM public.tb_home h
    JOIN public.tb_series s ON s.home_id = h.id AND s.kind = 'main' AND s.metric = 'power_w'
    JOIN LATERAL (
        SELECT name, version, artifact FROM public.tb_nilm_model
        WHERE active AND (home_id = h.id OR home_id IS NULL)
        ORDER BY home_id NULLS LAST LIMIT 1
    ) m ON true
    ORDER BY h.id
""")


async def targets(session: AsyncSession) -> list[Target]:
    """Homes with a main meter series and a model (their own, else the shared one)."""
    return [Target(**r._mapping) for r in await session.execute(TARGETS)]


async def _newest(session: AsyncSession, series_id: uuid.UUID) -> datetime | None:
    return await session.scalar(
        text("SELECT ts FROM public.tb_reading WHERE series_id = :s ORDER BY ts DESC LIMIT 1"),
        {"s": series_id},
    )


async def _start(session: AsyncSession, t: Target, history: timedelta) -> datetime | None:
    """The nilm checkpoint, or on a home's first pass its first reading within the history."""
    cp = await session.scalar(
        text(
            "SELECT last_ts FROM public.tb_ingest_checkpoint WHERE source = :src AND series_id = :s"
        ),
        {"src": SOURCE, "s": t.main_series},
    )
    if cp is not None:
        return cp
    return await session.scalar(
        text(
            "SELECT ts FROM public.tb_reading WHERE series_id = :s AND ts >= :lo "
            "ORDER BY ts LIMIT 1"
        ),
        {"s": t.main_series, "lo": datetime.now(UTC) - history},
    )


async def _read(session: AsyncSession, series_id: uuid.UUID, lo: datetime, hi: datetime):
    """Good readings only: flagged ones (REFIT `Issues`) were dropped from the training data and
    count as missing time in the aggregates too."""
    rows = (
        await session.execute(
            text(
                "SELECT ts, value FROM public.tb_reading "
                "WHERE series_id = :s AND ts >= :lo AND ts <= :hi AND quality & 1 = 0 "
                "ORDER BY ts"
            ),
            {"s": series_id, "lo": lo, "hi": hi},
        )
    ).all()
    ts = pd.DatetimeIndex([r.ts for r in rows]).tz_convert(UTC) if rows else pd.DatetimeIndex([])
    return ts, np.array([r.value for r in rows], dtype=np.float64)


async def _open_head(session: AsyncSession, series_id: uuid.UUID, lo: datetime) -> bool:
    """Whether the data runs on just before `lo` (so a run touching the slice head is not new)."""
    gap = (windows.MAX_FILL_BINS + 1) * windows.STEP.to_pytimedelta()
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM public.tb_reading "
                "WHERE series_id = :s AND ts >= :a AND ts < :b AND quality & 1 = 0)"
            ),
            {"s": series_id, "a": lo - gap, "b": lo},
        )
    )


def compute(
    bundle, plan: windows.Plan, tz: str, series: dict[str, uuid.UUID]
) -> list[tuple[datetime, uuid.UUID, float]]:
    """Run the model over the planned windows; rows for every covered bin from write_from on."""
    s, window = plan.series, bundle.window
    if not plan.starts:
        return []
    x = windows.model_inputs(s, plan.starts, window, tz)
    apps = windows.merge(len(s), plan.starts, window, bundle.predict(x))
    apps, other = windows.balance(s.to_numpy(), apps)
    keep = np.flatnonzero(~np.isnan(apps[0]) & s.notna().to_numpy())
    keep = keep[keep >= plan.write_from]
    ts = s.index[keep].to_pydatetime()
    columns = [*bundle.labels, OTHER]
    values = np.vstack([apps[:, keep], other[None, keep]])
    return [
        (when, series[label], float(v))
        for label, row in zip(columns, values, strict=True)
        for when, v in zip(ts, row, strict=True)
    ]


async def run_pass(
    sessions: async_sessionmaker[AsyncSession],
    t: Target,
    load: Callable[[Path], object],
    model_dir: Path,
    history: timedelta,
) -> PassResult:
    """One chunk for one home: read, infer, write estimates + move the checkpoint atomically.

    tb_reading is never touched. A failure leaves the checkpoint where it was and marks the run
    'failed' with the error, so the next pass retries the same chunk (the newest run wins).
    """
    async with sessions() as session, session.begin():
        start = await _start(session, t, history)
        newest = await _newest(session, t.main_series)
        if start is None or newest is None:
            return PassResult(None, 0, None, None, None)
        done = await session.scalar(
            text(
                "SELECT window_end FROM public.tb_inference_run WHERE home_id = :h "
                "AND status = 'ok' AND model_version = :v ORDER BY window_end DESC LIMIT 1"
            ),
            {"h": t.home_id, "v": t.model_version},
        )
        if done is not None and done >= newest:  # nothing new since the last successful pass
            return PassResult(None, 0, None, None, None)
        bundle = load(model_dir / t.artifact)
        window = bundle.window
        lo = start - 2 * window * windows.STEP.to_pytimedelta()
        hi = min(start + CHUNK, newest)
        open_head = await _open_head(session, t.main_series, lo)
        ts, watts = await _read(session, t.main_series, lo, hi)
        series = await ensure_devices(session, t.home_id, bundle.labels)
        run_id = await session.scalar(
            text(
                "INSERT INTO public.tb_inference_run "
                "(home_id, model_name, model_version, window_start, window_end, status) "
                "VALUES (:h, :n, :v, :a, :b, 'running') RETURNING run_id"
            ),
            {"h": t.home_id, "n": t.model_name, "v": t.model_version, "a": start, "b": hi},
        )
    try:
        plan = windows.plan(ts, watts, start, window, window // 2, open_head)
        rows = await asyncio.to_thread(compute, bundle, plan, t.timezone, series) if plan else []
        # No final bin in this slice (a gap longer than the chunk): skip past it.
        checkpoint = plan.final_until if plan and plan.final_until else None
        if checkpoint is None and hi < newest:
            checkpoint = hi
        async with sessions() as session, session.begin():
            written = await ingest_estimates(session, run_id, rows)
            if checkpoint is not None:
                await session.execute(
                    text(
                        "INSERT INTO public.tb_ingest_checkpoint (source, series_id, last_ts) "
                        "VALUES (:src, :s, :ts) ON CONFLICT (source, series_id) DO UPDATE SET "
                        "last_ts = GREATEST(public.tb_ingest_checkpoint.last_ts, EXCLUDED.last_ts),"
                        " updated_at = now()"
                    ),
                    {"src": SOURCE, "s": t.main_series, "ts": checkpoint},
                )
            await session.execute(
                text(
                    "UPDATE public.tb_inference_run SET status = 'ok', finished_at = now() "
                    "WHERE run_id = :r"
                ),
                {"r": run_id},
            )
    except Exception as exc:
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE public.tb_inference_run SET status = 'failed', finished_at = now(), "
                    "error = :e WHERE run_id = :r"
                ),
                {"e": f"{type(exc).__name__}: {exc}"[:2000], "r": run_id},
            )
        raise
    return PassResult(run_id, written, start, hi, newest)


async def run_home(
    engine: AsyncEngine,
    t: Target,
    load: Callable[[Path], object],
    model_dir: Path,
    history: timedelta,
) -> int:
    """Catch a home up to its newest reading, one chunk per pass. Returns estimate rows written.

    Holds a session advisory lock on the home for the whole catch-up, so two workers (or a
    manual run) never process the same home at once; a held lock means "skip, someone is on it".
    Estimates older than the 1m refresh policy are folded into the aggregates afterwards.
    """
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    key = f"nilm:{t.home_id}"
    async with engine.connect() as lock:
        got = await lock.scalar(LOCK, {"k": key})
        await lock.commit()
        if not got:
            return 0
        try:
            total, oldest = 0, None
            while True:
                r = await run_pass(sessions, t, load, model_dir, history)
                total += r.written
                if r.written and (oldest is None or r.start < oldest):
                    oldest = r.start
                if r.run_id is None or r.reached >= r.newest:
                    break
            if oldest is not None and oldest < datetime.now(UTC) - POLICY_1M:
                async with engine.connect() as c:
                    c = await c.execution_options(isolation_level="AUTOCOMMIT")
                    await backfill_aggregates(c, oldest, datetime.now(UTC))
            return total
        finally:
            await lock.execute(UNLOCK, {"k": key})
            await lock.commit()
