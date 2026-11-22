import asyncio
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
KEEP_HOURS = timedelta(days=400)
HOUR_COLS = ("p05", "p10", "p50", "p90", "p95", *(f"c_{g}" for g in GROUPS), "c_base")


async def _tz(s: AsyncSession, home_id: uuid.UUID) -> str:
    return await s.scalar(text("SELECT timezone FROM public.tb_home WHERE id = :h"), {"h": home_id})


def _midnight(now: datetime, tz: str) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    return datetime(local.year, local.month, local.day, tzinfo=ZoneInfo(tz)).astimezone(UTC)


async def active_bundle(s: AsyncSession, home_id: uuid.UUID) -> Bundle | None:
    row = await s.scalar(
        select(ExpectModel).where(ExpectModel.home_id == home_id, ExpectModel.active)
    )
    return from_row(row) if row else None


async def train_home(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> str | None:
    """Learn the home's model from its full local days before today (demo events left out);
    None when it has fewer than 28 of them. The new version becomes the active one."""
    tz = await _tz(s, home_id)
    hi = _midnight(now, tz)
    lo = hi - timedelta(days=settings.expect_history_days)
    y = await hourly_actual(s, home_id, lo, hi)
    y[(await excluded_hours(s, home_id, lo, hi)).reindex(y.index, fill_value=False)] = np.nan
    if not eligible(y, tz):
        return None
    x = await feature_frame(s, home_id, lo, hi, now)
    version = f"ctx-v2-{now.astimezone(UTC):%Y%m%d%H%M}"
    bundle = await asyncio.to_thread(fit, x, y, version=version, tz=tz)
    bundle.metrics["days"] = int(full_days(y, tz).sum())
    row = to_row(bundle)
    await s.execute(update(ExpectModel).where(ExpectModel.home_id == home_id).values(active=False))
    await s.execute(
        insert(ExpectModel)
        .values(home_id=home_id, active=True, trained_at=now, **row)
        .on_conflict_do_nothing()
    )
    await s.execute(
        delete(ExpectModel).where(
            ExpectModel.home_id == home_id,
            ExpectModel.active.is_(False),
            ExpectModel.trained_at < now - KEEP_MODELS,
        )
    )
    return version


async def refresh_home(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> int:
    """Expected kWh per hour from 70 days back to 35 days ahead with the active model."""
    bundle = await active_bundle(s, home_id)
    if bundle is None:
        return 0
    tz = await _tz(s, home_id)
    lo = _midnight(now, tz) - PAST
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
