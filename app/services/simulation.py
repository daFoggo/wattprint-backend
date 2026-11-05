"""NILM replay: stream one REFIT day through NILMFormer, minute by minute, into the energy schema.

Per minute the aggregate and the plug sub-meter readings go through `ingest_readings` (the path
a real meter uses) and the model estimates through `ingest_estimates`, all under one
`energy.inference_run`, committed after every minute so readers see the day grow.

Two rules of the database design shape the stored timestamps:
* `energy.reading` / `energy.device_estimate` drop data older than 400 days and the 1-minute
  aggregates only refresh the last 7 days, so a 2013-2015 REFIT day is stored under a recent
  calendar day (`replay_date`, default yesterday). The offset is a whole number of days plus
  the UTC+7 shift, so the day starts at local midnight and the hourly/daily aggregates line up.
* The model features (hour, weekday, month) and the 256-minute context use the original REFIT
  clock; only the stored `ts` is shifted.

The job state is in memory; the durable trace is the `energy.inference_run` row (window, status)
that the estimates point to. After an API restart a still-running replay cannot finish, and
`reconcile` marks its run as failed.
"""

import asyncio
import datetime as dt
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..cli.provision_refit import METADATA, meter_serial, provision_house
from ..config import settings
from ..database import SessionLocal
from ..ml import MODEL_NAME, MODEL_VERSION, NILM_APPLIANCES, WINDOW
from ..models import InferenceRun, User
from ..schemas.simulation import SimulationCreate, SimulationOut
from .disaggregation import VN, local_day_start, local_today, main_series
from .ingest import ReadingRow, ingest_estimates, ingest_readings

log = logging.getLogger(__name__)

SOURCE = "simulation"  # ops.ingest_batch.source of the replay's readings
MAX_REPLAY_AGE_DAYS = 6  # the 1-minute aggregate policy refreshes the last 7 days
CUTOFF = 10_000.0  # W; REFIT_DataBuilder clips the aggregate here before scaling
KEEP_JOBS = 50
ACTIVE = ("pending", "running")
_NS_PER_MINUTE = 60_000_000_000


class SimulationRefused(Exception):  # noqa: N818 - reads better than ...Error
    """The request cannot start a replay; `status` is the HTTP status to answer with."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Item:
    """One appliance of the replay: its sub-meter channel and the two series involved."""

    type: str  # catalog.device_type code
    device_id: uuid.UUID
    channel: str  # REFIT column, e.g. Appliance8
    plug_series: int  # kind 'plug': the sub-meter (ground truth)
    estimate_series: int  # kind 'device': the model estimate


@dataclass
class Job:
    run_id: int
    home_id: uuid.UUID
    house: int
    source_date: dt.date
    replay_date: dt.date
    rows_per_second: float
    csv_path: Path
    meter: str
    main_series: int
    items: list[Item]
    shift: dt.timedelta
    status: str = "pending"
    total_minutes: int | None = None
    done_minutes: int = 0
    error: str | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    cancel: bool = False


@dataclass
class DayData:
    grid: pd.DatetimeIndex  # UTC minutes: WINDOW - 1 of context, then the 1440 minutes of the day
    aggregate: np.ndarray  # W per grid minute; NaN where the CSV has no reading
    truth: dict[str, np.ndarray]  # appliance type -> sub-meter W per grid minute (gaps = 0)


JOBS: dict[int, Job] = {}
_TASKS: set[asyncio.Task] = set()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def replay_shift(source_date: dt.date, replay_date: dt.date) -> dt.timedelta:
    """Offset from the REFIT clock (UTC) to the stored clock.

    Maps the REFIT day's 00:00 UTC to 00:00 of `replay_date` in Asia/Ho_Chi_Minh.
    """
    source_start = dt.datetime.combine(source_date, dt.time.min, tzinfo=dt.UTC)
    return local_day_start(replay_date) - source_start


def load_day(csv_path: Path, day: dt.date, channels: dict[str, str]) -> DayData:
    """1-minute aggregate and sub-meter series of a REFIT CSV for one UTC day.

    `channels` maps appliance type to its CSV column. The grid starts WINDOW - 1 minutes before
    the day so the first minute of the day already has a full context window. The preprocessing
    equals training: 10 s mean, ffill up to 6 samples, clip to [0, 10 kW], 1 minute mean.

    The CSV is read in chunks and, being sorted by time, only up to the end of the day.
    """
    day_start = pd.Timestamp(day)  # naive midnight; the CSV Time column is UTC
    lo = day_start - pd.Timedelta(minutes=WINDOW - 1)
    hi = day_start + pd.Timedelta(days=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    lo_s, hi_s = lo.strftime(fmt), hi.strftime(fmt)

    parts = []
    columns = ["Time", "Aggregate", *channels.values()]
    # Time is compared as text (it sorts like a date) and only parsed for the rows we keep.
    for chunk in pd.read_csv(csv_path, usecols=columns, chunksize=500_000, dtype={"Time": str}):
        if chunk["Time"].iloc[0] >= hi_s:
            break
        keep = (chunk["Time"] >= lo_s) & (chunk["Time"] < hi_s)
        if keep.any():
            parts.append(chunk[keep])
    if not parts:
        raise ValueError("no data in the CSV for this date")

    df = pd.concat(parts)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("Time"))).tz_localize("UTC")
    grid = pd.date_range(
        lo.tz_localize("UTC"), hi.tz_localize("UTC"), freq="1min", inclusive="left"
    )

    def per_minute(column: str) -> pd.Series:
        return (
            df[column]
            .resample("10s")
            .mean()
            .ffill(limit=6)
            .clip(lower=0, upper=CUTOFF)
            .resample("1min")
            .mean()
            .reindex(grid)
        )

    aggregate = per_minute("Aggregate").to_numpy(dtype=np.float32)
    truth = {
        typ: per_minute(col).fillna(0).to_numpy(dtype=np.float32) for typ, col in channels.items()
    }
    return DayData(grid=grid, aggregate=aggregate, truth=truth)


def job_out(job: Job) -> SimulationOut:
    pct = None
    if job.total_minutes:
        pct = round(job.done_minutes / job.total_minutes * 100, 1)
    elif job.status == "done":
        pct = 100.0
    return SimulationOut(
        id=job.run_id,
        status=job.status,
        house=job.house,
        source_date=job.source_date,
        replay_date=job.replay_date,
        rows_per_second=job.rows_per_second,
        total_minutes=job.total_minutes,
        done_minutes=job.done_minutes,
        progress_pct=pct,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def reconcile(db: AsyncSession, home_id: uuid.UUID) -> None:
    """Mark replays left 'running' by a process that died (restart, --reload) as failed."""
    active = [j.run_id for j in JOBS.values() if j.status in ACTIVE]
    await db.execute(
        text(
            "UPDATE energy.inference_run SET status = 'failed', finished_at = now() "
            "WHERE home_id = :h AND model_name = :m AND status = 'running' "
            "AND NOT (run_id = ANY(:ids))"
        ),
        {"h": home_id, "m": MODEL_NAME, "ids": active},
    )
    await db.commit()


async def find(db: AsyncSession, home_id: uuid.UUID, run_id: int) -> SimulationOut | None:
    """A replay of this home: live state if this process runs it, else the stored run."""
    job = JOBS.get(run_id)
    if job is not None and job.home_id == home_id:
        return job_out(job)
    row = (
        await db.execute(
            text(
                "SELECT status, window_start, started_at, finished_at FROM energy.inference_run "
                "WHERE run_id = :r AND home_id = :h AND model_name = :m"
            ),
            {"r": run_id, "h": home_id, "m": MODEL_NAME},
        )
    ).first()
    if row is None:
        return None
    return SimulationOut(
        id=run_id,
        status={"ok": "done", "failed": "failed"}.get(row.status, "running"),
        replay_date=row.window_start.astimezone(VN).date(),
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def cancel(home_id: uuid.UUID, run_id: int) -> bool:
    """Ask a running replay of this home to stop after the current minute."""
    job = JOBS.get(run_id)
    if job is None or job.home_id != home_id or job.status not in ACTIVE:
        return False
    job.cancel = True
    return True


async def _estimate_series(db: AsyncSession, home_id: uuid.UUID, device_id: uuid.UUID) -> int:
    """The 'device' series that holds the model estimates of a device (created once)."""
    params = {"h": home_id, "d": device_id}
    await db.execute(
        text(
            "INSERT INTO energy.series (home_id, kind, device_id, metric, unit) "
            "VALUES (:h, 'device', :d, 'power_w', 'W') "
            "ON CONFLICT ON CONSTRAINT uq_series_home_kind_device_metric DO NOTHING"
        ),
        params,
    )
    return await db.scalar(
        text(
            "SELECT series_id FROM energy.series "
            "WHERE home_id = :h AND kind = 'device' AND device_id = :d AND metric = 'power_w'"
        ),
        params,
    )


async def appliance_items(db: AsyncSession, home_id: uuid.UUID) -> list[Item]:
    """The appliances of a home the model covers, with their series (estimate ones created)."""
    plugs = (
        await db.execute(
            text(
                "SELECT s.series_id, s.source_channel, d.id AS device_id, "
                "d.device_type_code AS type FROM energy.series s "
                "JOIN core.device d ON d.id = s.device_id "
                "WHERE s.home_id = :h AND s.kind = 'plug' AND s.metric = 'power_w' "
                "ORDER BY s.source_channel"
            ),
            {"h": home_id},
        )
    ).all()
    items = []
    for typ in NILM_APPLIANCES:
        plug = next((p for p in plugs if p.type == typ), None)
        if plug is not None:
            estimate = await _estimate_series(db, home_id, plug.device_id)
            items.append(Item(typ, plug.device_id, plug.source_channel, plug.series_id, estimate))
    return items


async def start(db: AsyncSession, user: User, body: SimulationCreate) -> Job:
    """Validate, provision the REFIT home of the user if needed and launch the replay."""
    house = body.house
    if str(house) not in METADATA:
        raise SimulationRefused(422, f"unknown REFIT house {house}")
    csv_path = Path(settings.refit_csv_dir) / f"CLEAN_House{house}.csv"
    if not csv_path.is_file():
        raise SimulationRefused(422, f"CSV not found in the container: {csv_path}")
    today = local_today()
    replay = body.replay_date or today - dt.timedelta(days=1)
    if not today - dt.timedelta(days=MAX_REPLAY_AGE_DAYS) <= replay <= today:
        raise SimulationRefused(
            422,
            f"replay_date must be within the last {MAX_REPLAY_AGE_DAYS} days (today is {today})",
        )

    try:
        home_id = await provision_house(db, house, user.email)
    except ValueError as exc:
        await db.rollback()
        raise SimulationRefused(409, str(exc)) from None
    await db.commit()
    await reconcile(db, home_id)
    busy = next((j for j in JOBS.values() if j.home_id == home_id and j.status in ACTIVE), None)
    if busy is not None:
        raise SimulationRefused(409, f"simulation {busy.run_id} is still running for this home")

    items = await appliance_items(db, home_id)
    if not items:
        raise SimulationRefused(
            422, f"REFIT house {house} has none of: {', '.join(NILM_APPLIANCES)}"
        )
    main = await main_series(db, home_id)

    shift = replay_shift(body.date, replay)
    window_start = local_day_start(replay)
    run = InferenceRun(
        home_id=home_id,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        window_start=window_start,
        window_end=window_start + dt.timedelta(days=1),
        status="running",
    )
    db.add(run)
    await db.flush()
    run_id = run.run_id
    await db.commit()

    job = Job(
        run_id=run_id,
        home_id=home_id,
        house=house,
        source_date=body.date,
        replay_date=replay,
        rows_per_second=body.rows_per_second,
        csv_path=csv_path,
        meter=meter_serial(house),
        main_series=main,
        items=items,
        shift=shift,
    )
    _prune()
    JOBS[run_id] = job
    task = asyncio.create_task(_run(job))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return job


def _prune() -> None:
    finished = [j.run_id for j in JOBS.values() if j.status not in ACTIVE]
    for run_id in finished[: max(0, len(JOBS) - KEEP_JOBS)]:
        del JOBS[run_id]


async def _wipe(db: AsyncSession, job: Job) -> None:
    """Remove what an earlier replay stored for this home and day (the latest replay wins)."""
    start = local_day_start(job.replay_date)
    params = {"a": start, "b": start + dt.timedelta(days=1)}
    readings = [job.main_series, *(i.plug_series for i in job.items)]
    estimates = [i.estimate_series for i in job.items]
    await db.execute(
        text("DELETE FROM energy.reading WHERE series_id = ANY(:ids) AND ts >= :a AND ts < :b"),
        {"ids": readings, **params},
    )
    await db.execute(
        text(
            "DELETE FROM energy.device_estimate "
            "WHERE series_id = ANY(:ids) AND ts >= :a AND ts < :b"
        ),
        {"ids": estimates, **params},
    )
    await db.commit()


async def _finish_run(job: Job, status: str, last_ts: dt.datetime | None) -> None:
    """Close the inference_run; a cancelled replay keeps the window it actually covered."""
    window_end = last_ts + dt.timedelta(minutes=1) if last_ts is not None else None
    try:
        async with SessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE energy.inference_run SET status = :s, finished_at = now(), "
                    "window_end = coalesce(:we, window_end) WHERE run_id = :r"
                ),
                {"s": status, "we": window_end, "r": job.run_id},
            )
            await db.commit()
    except Exception:
        log.exception("could not close inference_run %s", job.run_id)


async def _run(job: Job) -> None:
    last_ts: dt.datetime | None = None
    try:
        from ..ml import nilm  # imported here: torch is heavy and optional for the rest of the API

        job.status = "running"
        job.started_at = _now()
        await asyncio.to_thread(nilm.get_models)  # loads the checkpoints on the first replay
        channels = {i.type: i.channel for i in job.items}
        data = await asyncio.to_thread(load_day, job.csv_path, job.source_date, channels)

        aggregate = np.nan_to_num(data.aggregate, nan=0.0)  # gaps enter the context window as 0
        has_reading = ~np.isnan(data.aggregate)
        minutes = [j for j in range(WINDOW - 1, len(data.grid)) if has_reading[j]]
        if not minutes:
            raise ValueError("the CSV has no reading for this date")
        job.total_minutes = len(minutes)

        async with SessionLocal() as db:
            await _wipe(db, job)
            interval = 1.0 / job.rows_per_second
            for n, j in enumerate(minutes, start=1):
                if job.cancel:
                    break
                began = time.monotonic()
                window = aggregate[j - WINDOW + 1 : j + 1][None, :]  # the last 256 minutes
                start_minute = int(data.grid[j - WINDOW + 1].value // _NS_PER_MINUTE)
                pred = await asyncio.to_thread(nilm.predict, [start_minute], window)

                ts = (data.grid[j] + job.shift).to_pydatetime()
                readings = [ReadingRow(ts, "Aggregate", float(aggregate[j]))]
                readings += [
                    ReadingRow(ts, i.channel, float(data.truth[i.type][j])) for i in job.items
                ]
                await ingest_readings(db, job.meter, readings, SOURCE)
                await ingest_estimates(
                    db,
                    job.run_id,
                    [(ts, i.estimate_series, float(pred[i.type][0, -1])) for i in job.items],
                )
                await db.commit()
                job.done_minutes = n
                last_ts = ts
                await asyncio.sleep(max(0.0, interval - (time.monotonic() - began)))

        job.status = "cancelled" if job.cancel else "done"
        await _finish_run(job, "ok", last_ts if job.cancel else None)
    except Exception as exc:
        log.exception("replay %s failed", job.run_id)
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"[:500]
        await _finish_run(job, "failed", None)
    finally:
        job.finished_at = _now()
