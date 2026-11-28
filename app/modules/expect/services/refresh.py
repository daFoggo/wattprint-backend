import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from ..models import ExpectHourly, ExpectModel
from .features import GROUPS, excluded_hours, feature_frame, hourly_actual
from .predict import predict
from .train import Bundle, eligible, fit, from_row, full_days, to_row

PAST = timedelta(days=70)  # recomputed each refresh: two cycles back, for explanations
AHEAD = timedelta(days=35)  # past any running cycle's end
KEEP_MODELS = timedelta(days=14)  # inactive versions kept so snapshots can still be compared
RETRAIN = timedelta(days=7)  # spec C1: relearn when 7 more days are in
KEEP_HOURS = timedelta(days=400)
NONE = "'00000000-0000-0000-0000-000000000000'::uuid"  # the home's own model
HOUR_COLS = ("p05", "p10", "p50", "p90", "p95", *(f"c_{g}" for g in GROUPS), "c_base")


async def _tz(s: AsyncSession, home_id: uuid.UUID) -> str:
    return await s.scalar(text("SELECT timezone FROM public.tb_home WHERE id = :h"), {"h": home_id})


def _midnight(now: datetime, tz: str) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    return datetime(local.year, local.month, local.day, tzinfo=ZoneInfo(tz)).astimezone(UTC)


def _owner(home_id: uuid.UUID, device_id: uuid.UUID | None):
    """The home's own model (device_id NULL) or one device's."""
    dev = (
        ExpectModel.device_id.is_(None) if device_id is None else ExpectModel.device_id == device_id
    )
    return (ExpectModel.home_id == home_id, dev)


async def active_bundle(
    s: AsyncSession, home_id: uuid.UUID, device_id: uuid.UUID | None = None
) -> Bundle | None:
    row = await s.scalar(select(ExpectModel).where(*_owner(home_id, device_id), ExpectModel.active))
    return from_row(row) if row else None


async def last_trained(
    s: AsyncSession, home_id: uuid.UUID, device_id: uuid.UUID | None = None
) -> datetime | None:
    return await s.scalar(
        select(ExpectModel.trained_at).where(*_owner(home_id, device_id), ExpectModel.active)
    )


def fit_bundle(x: pd.DataFrame, y: pd.Series, version: str, tz: str) -> Bundle:
    bundle = fit(x, y, version=version, tz=tz)
    bundle.metrics["days"] = int(full_days(y, tz).sum())
    return bundle


async def store(
    s: AsyncSession, home_id: uuid.UUID, device_id: uuid.UUID | None, bundle: Bundle, now: datetime
) -> None:
    """Make `bundle` the owner's active model; older inactive versions go after KEEP_MODELS."""
    row = to_row(bundle)
    # Two trainers of one owner (the nightly job and a manual run) take turns, else both
    # deactivate and both insert an active row.
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"expect:{home_id}:{device_id}"},
    )
    await s.execute(update(ExpectModel).where(*_owner(home_id, device_id)).values(active=False))
    # the same version again (two runs in a second) replaces it, still active
    await s.execute(
        text(
            "INSERT INTO public.tb_expect_model (home_id, device_id, version, trained_at, "
            "features, boosters, residuals, widen, metrics, active) VALUES (:h, :d, :v, :t, :f, "
            "CAST(:b AS jsonb), :r, CAST(:w AS jsonb), CAST(:m AS jsonb), true) "
            f"ON CONFLICT (home_id, COALESCE(device_id, {NONE}), version) DO UPDATE SET "
            "trained_at = EXCLUDED.trained_at, features = EXCLUDED.features, "
            "boosters = EXCLUDED.boosters, residuals = EXCLUDED.residuals, "
            "widen = EXCLUDED.widen, metrics = EXCLUDED.metrics, active = true"
        ),
        {
            "h": home_id,
            "d": device_id,
            "v": row["version"],
            "t": now,
            "f": row["features"],
            "b": json.dumps(row["boosters"]),
            "r": row["residuals"],
            "w": json.dumps(row["widen"]),
            "m": json.dumps(row["metrics"]),
        },
    )
    await s.execute(
        delete(ExpectModel).where(
            *_owner(home_id, device_id),
            ExpectModel.active.is_(False),
            ExpectModel.trained_at < now - KEEP_MODELS,
        )
    )


def due(trained_at: datetime | None, now: datetime) -> bool:
    """A model is relearnt weekly: a version that lives 7 days lets "why the forecast changed"
    compare day to day (a new version cannot be compared with yesterday's)."""
    return trained_at is None or now - trained_at >= RETRAIN


async def train_home(
    s: AsyncSession, home_id: uuid.UUID, now: datetime, force: bool = False
) -> str | None:
    """Learn the home's model from its full local days before today (demo events left out),
    once a week unless forced; None when not due or with fewer than 28 full days. The new
    version becomes the active one."""
    if not force and not due(await last_trained(s, home_id), now):
        return None
    tz = await _tz(s, home_id)
    hi = _midnight(now, tz)
    lo = hi - timedelta(days=settings.expect_history_days)
    y = await hourly_actual(s, home_id, lo, hi)
    y[(await excluded_hours(s, home_id, lo, hi)).reindex(y.index, fill_value=False)] = np.nan
    if not eligible(y, tz):
        return None
    x = await feature_frame(s, home_id, lo, hi, now)
    version = f"ctx-v3-{now.astimezone(UTC):%Y%m%d%H%M%S}"  # v3: the centre is the mean
    bundle = await asyncio.to_thread(fit_bundle, x, y, version, tz)
    previous = await active_bundle(s, home_id)
    if previous and "backtest" in previous.metrics:  # kept until a new backtest replaces it
        bundle.metrics["backtest"] = previous.metrics["backtest"]
    await store(s, home_id, None, bundle, now)
    return version


async def refresh_home(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> int:
    """Expected kWh per hour from 70 days back to 35 days ahead with the active model."""
    bundle = await active_bundle(s, home_id)
    if bundle is None:
        return 0
    tz = await _tz(s, home_id)
    lo = _midnight(now, tz) - PAST
    erased = await s.scalar(
        text("SELECT history_erased_before FROM public.tb_home WHERE id = :h"), {"h": home_id}
    )
    lo = max(lo, erased) if erased else lo  # what the owner erased stays erased
    x = await feature_frame(s, home_id, lo, now + AHEAD, now)
    p = predict(bundle, x).dropna(subset=list(HOUR_COLS))
    rows = [
        {
            "home_id": home_id,
            "ts": ts.to_pydatetime(),
            "model_version": bundle.version,
            **{c: float(r[c]) for c in HOUR_COLS},
        }
        for ts, r in p.iterrows()
    ]
    for i in range(0, len(rows), 2000):
        stmt = insert(ExpectHourly).values(rows[i : i + 2000])
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=["home_id", "ts"],
                set_={c: stmt.excluded[c] for c in (*HOUR_COLS, "model_version")},
            )
        )
    await s.execute(
        delete(ExpectHourly).where(
            ExpectHourly.home_id == home_id, ExpectHourly.ts < now - KEEP_HOURS
        )
    )
    return len(rows)


async def expected(s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime) -> pd.DataFrame:
    """Stored expectations over [lo, hi), indexed by hour (UTC); empty without a model."""
    rows = (
        (
            await s.execute(
                select(ExpectHourly)
                .where(ExpectHourly.home_id == home_id, ExpectHourly.ts >= lo, ExpectHourly.ts < hi)
                .order_by(ExpectHourly.ts)
            )
        )
        .scalars()
        .all()
    )
    frame = pd.DataFrame(
        [
            {"ts": r.ts, "model_version": r.model_version, **{c: getattr(r, c) for c in HOUR_COLS}}
            for r in rows
        ],
        columns=["ts", "model_version", *HOUR_COLS],
    )
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame.set_index("ts")
