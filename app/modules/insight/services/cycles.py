import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.energy.api import on_w, runs

from ..models import DeviceCycle

KEEP = timedelta(days=35)  # first pass and the oldest minute a pass re-reads


async def refresh_cycles(session: AsyncSession, home_id: uuid.UUID, until: datetime) -> None:
    """Store the device runs NILM estimated up to `until` (ended ones only), from where the last
    stored run of each device ended. "Other" is the background, one endless run: skipped."""
    devices = await session.execute(
        text(
            "SELECT d.id, d.device_type_code AS type, s.series_id FROM public.tb_device d "
            "JOIN public.tb_series s ON s.device_id = d.id AND s.kind = 'device' "
            "WHERE d.home_id = :h AND d.device_type_code <> 'other'"
        ),
        {"h": home_id},
    )
    for d in devices.all():
        last = await session.scalar(
            select(func.max(DeviceCycle.end_ts)).where(DeviceCycle.device_id == d.id)
        )
        since = max(last or until - KEEP, until - KEEP)
        minutes = [
            (r.bucket, float(r.avg_w), float(r.energy_wh), float(r.max_w))
            for r in await session.execute(
                text(
                    "SELECT bucket, avg_w, energy_wh, max_w FROM public.device_estimate_1m "
                    "WHERE series_id = :s AND bucket >= :lo AND bucket < :hi ORDER BY bucket"
                ),
                {"s": d.series_id, "lo": since, "hi": until},
            )
        ]
        done = [c for c in runs([m[:3] for m in minutes], on_w(d.type), until) if c.end]
        if not done:
            continue
        rows, i = [], 0
        for c in done:  # runs and minutes are both in time order: one pass for the peaks
            while minutes[i][0] < c.start:
                i += 1
            peak = 0.0
            while i < len(minutes) and minutes[i][0] < c.end:
                peak = max(peak, minutes[i][3])
                i += 1
            rows.append(
                {
                    "home_id": home_id,
                    "device_id": d.id,
                    "start_ts": c.start,
                    "end_ts": c.end,
                    "energy_wh": c.kwh * 1000,
                    "peak_w": peak,
                }
            )
        for k in range(0, len(rows), 5000):  # asyncpg takes at most 32767 parameters
            await session.execute(
                insert(DeviceCycle).values(rows[k : k + 5000]).on_conflict_do_nothing()
            )
