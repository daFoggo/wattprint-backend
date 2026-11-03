"""Replay one REFIT day minute by minute: store data, run NILMFormer right away, store result."""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, text, update

from app.core.config import settings
from app.db.session import SessionLocal

from .models import SimulationJob
from .schemas import SimulationOut

log = logging.getLogger(__name__)

WINDOW = 256
CUTOFF = 10_000.0
# REFIT house 2 sub-meters (see HOUSES_Labels); verify before using another house's CSV
TRUTH_COLS = {"washing_machine": "Appliance2", "dishwasher": "Appliance3",
              "microwave": "Appliance5", "kettle": "Appliance8"}
_COLS = ["Time", "Aggregate", *TRUTH_COLS.values()]

_ACTIVE: set[int] = set()
_TASKS: set[asyncio.Task] = set()

_INS_AGG = text("INSERT INTO aggregate_power (ts, house_id, watts) VALUES (:ts, :h, :w) "
                "ON CONFLICT (house_id, ts) DO UPDATE SET watts = EXCLUDED.watts")
_INS_PRED = text("INSERT INTO appliance_power (ts, house_id, appliance, watts) VALUES (:ts, :h, :a, :w) "
                 "ON CONFLICT (house_id, appliance, ts) DO UPDATE SET watts = EXCLUDED.watts")
_INS_TRUTH = text("INSERT INTO appliance_truth (ts, house_id, appliance, watts) VALUES (:ts, :h, :a, :w) "
                  "ON CONFLICT (house_id, appliance, ts) DO UPDATE SET watts = EXCLUDED.watts")


def job_out(job: SimulationJob) -> SimulationOut:
    if job.total_minutes:
        pct = round(job.done_minutes / job.total_minutes * 100, 1)
    else:
        pct = 100.0 if job.status == "done" else 0.0
    return SimulationOut(
        id=job.id, house_id=job.house_id, day=job.day, status=job.status,
        rows_per_second=job.rows_per_second, total_minutes=job.total_minutes,
        done_minutes=job.done_minutes, progress_pct=pct, error=job.error,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
    )


async def fail_orphans(db) -> None:
    """Jobs left 'running' by a process that died (restart / --reload) can never finish."""
    await db.execute(
        update(SimulationJob)
        .where(SimulationJob.status.in_(("pending", "running")), SimulationJob.id.notin_(list(_ACTIVE)))
        .values(status="failed", error="interrupted (API restarted)", finished_at=func.now())
    )
    await db.commit()


def start_job(job_id: int) -> None:
    _ACTIVE.add(job_id)
    task = asyncio.create_task(_run_job(job_id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _load_minutes(csv_path: str, day: date):
    """1-minute aggregate + ground truth for [day-255min, day+1d), same preprocessing as training."""
    day_start = pd.Timestamp(day)
    lo = day_start - pd.Timedelta(minutes=WINDOW - 1)
    hi = day_start + pd.Timedelta(days=1)
    lo_s, hi_s = lo.strftime("%Y-%m-%d %H:%M:%S"), hi.strftime("%Y-%m-%d %H:%M:%S")

    parts = []
    # compare Time as text (sortable) and parse only the rows we keep; stop once past the day
    for chunk in pd.read_csv(csv_path, usecols=_COLS, chunksize=500_000, dtype={"Time": str}):
        if chunk["Time"].iloc[0] >= hi_s:
            break
        keep = (chunk["Time"] >= lo_s) & (chunk["Time"] < hi_s)
        if keep.any():
            parts.append(chunk[keep])
    if not parts:
        raise ValueError("no data in the CSV for this date")

    df = pd.concat(parts)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("Time"))).tz_localize("UTC")

    def to_min(s):
        return (s.resample("10s").mean().ffill(limit=6)
                .clip(lower=0, upper=CUTOFF).resample("1min").mean())

    grid = pd.date_range(lo.tz_localize("UTC"), hi.tz_localize("UTC"), freq="1min", inclusive="left")
    agg = to_min(df["Aggregate"]).reindex(grid)
    truth = {n: to_min(df[c]).reindex(grid).fillna(0).to_numpy() for n, c in TRUTH_COLS.items()}
    return grid, agg, truth


async def _run_job(job_id: int) -> None:
    try:
        from app.ml.nilm import get_models, predict  # imported lazily: torch is heavy

        async with SessionLocal() as db:
            job = await db.get(SimulationJob, job_id)
            job.status, job.started_at = "running", datetime.now(timezone.utc)
            await db.commit()

            await asyncio.to_thread(get_models)  # load the 4 checkpoints (first job only)
            grid, agg, truth = await asyncio.to_thread(_load_minutes, settings.refit_csv_path, job.day)

            agg_f = agg.fillna(0).to_numpy(np.float32)
            valid = agg.notna().to_numpy()
            idx = [j for j in range(WINDOW - 1, len(grid)) if valid[j]]
            if not idx:
                raise ValueError("no valid minutes for this date")
            job.total_minutes = len(idx)

            # overwrite policy: wipe previous results of this house for this day
            a = grid[WINDOW - 1].to_pydatetime()
            b = grid[-1].to_pydatetime() + timedelta(minutes=1)
            for table in ("appliance_power", "aggregate_power", "appliance_truth"):
                await db.execute(text(f"DELETE FROM {table} WHERE house_id = :h AND ts >= :a AND ts < :b"),
                                 {"h": job.house_id, "a": a, "b": b})
            await db.commit()

            interval = 1.0 / job.rows_per_second
            for n, j in enumerate(idx, start=1):
                t0 = time.monotonic()
                window = agg_f[j - WINDOW + 1 : j + 1][None, :]               # last 256 minutes
                start_min = int(grid[j - WINDOW + 1].value // 60_000_000_000)  # minutes since epoch
                pred = await asyncio.to_thread(predict, [start_min], window)

                ts = grid[j].to_pydatetime()
                await db.execute(_INS_AGG, {"ts": ts, "h": job.house_id, "w": float(agg_f[j])})
                await db.execute(_INS_PRED, [
                    {"ts": ts, "h": job.house_id, "a": name, "w": float(arr[0, -1])}
                    for name, arr in pred.items()
                ])
                await db.execute(_INS_TRUTH, [
                    {"ts": ts, "h": job.house_id, "a": name, "w": float(vals[j])}
                    for name, vals in truth.items()
                ])
                job.done_minutes = n
                await db.commit()
                await asyncio.sleep(max(0.0, interval - (time.monotonic() - t0)))

            job.status, job.finished_at = "done", datetime.now(timezone.utc)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("simulation %s failed", job_id)
        async with SessionLocal() as db:
            await db.execute(
                update(SimulationJob).where(SimulationJob.id == job_id)
                .values(status="failed", error=f"{type(exc).__name__}: {exc}"[:500], finished_at=func.now())
            )
            await db.commit()
    finally:
        _ACTIVE.discard(job_id)