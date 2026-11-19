import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")  # tb_home.timezone is CHECKed to this
# shortcut: on/off thresholds per device type are the current NILM bundle's on_threshold_w; move
# them into tb_nilm_model when bundles start to differ.
ON_W = {
    "fridge_freezer": 50.0,
    "freezer": 50.0,
    "washing_machine": 20.0,
    "dishwasher": 10.0,
    "microwave": 200.0,
    "toaster": 200.0,
    "kettle": 1000.0,
}
DEFAULT_ON_W = 20.0
OTHER_ON_W = 1.0  # "other" is the background: on whenever it draws anything
RUN_GAP = timedelta(minutes=2)  # off minutes inside one run (a kettle reboil, a pause)
MIN_RUN_WH = 5.0  # smaller "runs" are NILM noise just over the threshold (a 1-min kettle ~33 Wh)
LIVE = timedelta(minutes=10)  # an estimate older than this is not "now"


@dataclass
class DeviceRow:
    id: uuid.UUID
    name: str
    room: str | None
    type: str
    show_on_timeline: bool
    series_id: uuid.UUID
    typical_w: int | None
    tip: str | None
    on_w: float
    watts: float = 0.0
    on: bool = False
    today_kwh: float = 0.0
    month_kwh: float = 0.0
    week_kwh: list[float] = field(default_factory=list)


@dataclass
class Cycle:
    start: datetime
    end: datetime | None  # None while still running
    kwh: float


@dataclass
class DeviceDetail:
    device: DeviceRow
    avg_on_w: float
    peak_w: float
    home_share: float
    days: list[tuple[date, float]]
    power: list[tuple[datetime, float]]
    cycles: list[Cycle]


def local_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=LOCAL).astimezone(UTC)


def on_w(code: str) -> float:
    return OTHER_ON_W if code == "other" else ON_W.get(code, DEFAULT_ON_W)


async def _rows(session: AsyncSession, home_id: uuid.UUID) -> list[DeviceRow]:
    """The home's devices that have an estimated ('device') series: what NILM found."""
    result = await session.execute(
        text(
            "SELECT d.id, d.name, d.room, d.device_type_code AS type, d.show_on_timeline, "
            "s.series_id, t.typical_watts AS typical_w, t.tip_text AS tip "
            "FROM public.tb_device d "
            "JOIN public.tb_series s ON s.device_id = d.id AND s.kind = 'device' "
            "AND s.metric = 'power_w' "
            "JOIN public.cat_device_type t ON t.code = d.device_type_code "
            "WHERE d.home_id = :h AND d.deleted_at IS NULL AND d.merged_into_id IS NULL "
            "ORDER BY d.created_at"
        ),
        {"h": home_id},
    )
    return [DeviceRow(**r._mapping, on_w=on_w(r.type)) for r in result]


async def _fill(session: AsyncSession, rows: list[DeviceRow], now: datetime) -> None:
    """Power now, today, this month (from the 1st) and the last 7 local days, per device."""
    if not rows:
        return
    ids = [r.series_id for r in rows]
    today = now.astimezone(LOCAL).date()
    month = today.replace(day=1)
    since = min(month, today - timedelta(days=6))
    latest = dict(
        (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (series_id) series_id, value "
                    "FROM public.tb_device_estimate "
                    "WHERE series_id = ANY(:ids) AND ts > :lo AND ts <= :now "
                    "ORDER BY series_id, ts DESC"
                ),
                {"ids": ids, "lo": now - LIVE, "now": now},
            )
        ).all()
    )
    daily: dict[tuple[uuid.UUID, date], float] = {}
    for r in await session.execute(
        text(
            "SELECT series_id, bucket, energy_wh FROM public.device_estimate_1d "
            "WHERE series_id = ANY(:ids) AND bucket >= :lo AND bucket <= :now"
        ),
        {"ids": ids, "lo": local_midnight(since), "now": now},
    ):
        daily[(r.series_id, r.bucket.astimezone(LOCAL).date())] = r.energy_wh / 1000
    for row in rows:
        row.watts = float(latest.get(row.series_id, 0.0))
        row.on = row.watts >= row.on_w
        row.today_kwh = daily.get((row.series_id, today), 0.0)
        row.month_kwh = sum(
            kwh for (sid, d), kwh in daily.items() if sid == row.series_id and d >= month
        )
        row.week_kwh = [
            daily.get((row.series_id, today - timedelta(days=6 - i)), 0.0) for i in range(7)
        ]


async def devices(session: AsyncSession, home_id: uuid.UUID, now: datetime) -> list[DeviceRow]:
    rows = await _rows(session, home_id)
    await _fill(session, rows, now)
    return rows


def runs(minutes: list[tuple[datetime, float, float]], on_w: float, now: datetime) -> list[Cycle]:
    """Group on-minutes (bucket, avg_w, energy_wh) into runs; gaps up to RUN_GAP stay one run.

    A run whose last on-minute is the newest minute is still going (end None). Runs under
    MIN_RUN_WH are dropped.
    """
    out: list[Cycle] = []
    start = last = None
    wh = 0.0
    for bucket, avg_w, energy_wh in minutes:
        if avg_w < on_w:
            continue
        if last is not None and bucket - last > RUN_GAP:
            out.append(Cycle(start, last + timedelta(minutes=1), wh / 1000))
            start, wh = None, 0.0
        if start is None:
            start = bucket
        last, wh = bucket, wh + energy_wh
    if start is not None:
        running = now - last <= timedelta(minutes=2)
        out.append(Cycle(start, None if running else last + timedelta(minutes=1), wh / 1000))
    return [c for c in out if c.kwh * 1000 >= MIN_RUN_WH]


async def _cycles(
    session: AsyncSession, rows: list[DeviceRow], since: datetime, now: datetime
) -> dict[uuid.UUID, list[Cycle]]:
    by_series: dict[uuid.UUID, list[tuple[datetime, float, float]]] = {
        r.series_id: [] for r in rows
    }
    if not rows:
        return {}
    for r in await session.execute(
        text(
            "SELECT series_id, bucket, avg_w, energy_wh FROM public.device_estimate_1m "
            "WHERE series_id = ANY(:ids) AND bucket >= :lo AND bucket <= :now "
            "ORDER BY series_id, bucket"
        ),
        {"ids": list(by_series), "lo": since, "now": now},
    ):
        by_series[r.series_id].append((r.bucket, float(r.avg_w), float(r.energy_wh)))
    return {r.id: runs(by_series[r.series_id], r.on_w, now) for r in rows}


async def device_detail(
    session: AsyncSession, home_id: uuid.UUID, device_id: uuid.UUID, now: datetime
) -> DeviceDetail | None:
    rows = await _rows(session, home_id)
    row = next((r for r in rows if r.id == device_id), None)
    if row is None:
        return None
    await _fill(session, [row], now)
    today = now.astimezone(LOCAL).date()
    month = local_midnight(today.replace(day=1))
    stats = (
        await session.execute(
            text(
                "SELECT avg(avg_w) FILTER (WHERE avg_w >= :on) AS avg_on, max(max_w) AS peak "
                "FROM public.device_estimate_1m WHERE series_id = :s AND bucket >= :lo "
                "AND bucket <= :now"
            ),
            {"s": row.series_id, "on": row.on_w, "lo": month, "now": now},
        )
    ).one()
    home_wh = await session.scalar(
        text(
            "SELECT sum(r.energy_wh) FROM public.reading_1d r JOIN public.tb_series s "
            "USING (series_id) WHERE s.home_id = :h AND s.kind = 'main' "
            "AND r.bucket >= :lo AND r.bucket <= :now"
        ),
        {"h": home_id, "lo": month, "now": now},
    )
    days = []
    day = today.replace(day=1)
    daily = {
        r.bucket.astimezone(LOCAL).date(): r.energy_wh / 1000
        for r in await session.execute(
            text(
                "SELECT bucket, energy_wh FROM public.device_estimate_1d "
                "WHERE series_id = :s AND bucket >= :lo AND bucket <= :now"
            ),
            {"s": row.series_id, "lo": month, "now": now},
        )
    }
    while day <= today:
        days.append((day, daily.get(day, 0.0)))
        day += timedelta(days=1)
    power = [
        (r.step, float(r.watts))
        for r in await session.execute(
            text(
                "SELECT time_bucket('5 minutes', bucket) AS step, avg(avg_w) AS watts "
                "FROM public.device_estimate_1m WHERE series_id = :s AND bucket >= :lo "
                "AND bucket <= :now GROUP BY 1 ORDER BY 1"
            ),
            {"s": row.series_id, "lo": now - timedelta(days=1), "now": now},
        )
    ]
    cycles = (await _cycles(session, [row], now - timedelta(days=1), now))[row.id]
    return DeviceDetail(
        device=row,
        avg_on_w=float(stats.avg_on or 0.0),
        peak_w=float(stats.peak or 0.0),
        home_share=row.month_kwh * 1000 / home_wh if home_wh else 0.0,
        days=days,
        power=power,
        cycles=cycles,
    )


async def activity(
    session: AsyncSession, home_id: uuid.UUID, now: datetime
) -> list[tuple[DeviceRow, Cycle]]:
    """Runs started in the last 24 hours of the devices shown on the timeline, oldest first."""
    rows = [r for r in await _rows(session, home_id) if r.show_on_timeline]
    since = now - timedelta(days=1)
    cycles = await _cycles(session, rows, since, now)
    out = [(r, c) for r in rows for c in cycles[r.id] if c.start >= since]
    return sorted(out, key=lambda rc: rc[1].start)


async def analyzed_until(session: AsyncSession, home_id: uuid.UUID) -> datetime | None:
    """The newest reading NILM has turned into device estimates (end of the last good run)."""
    return await session.scalar(
        text(
            "SELECT window_end FROM public.tb_inference_run WHERE home_id = :h AND status = 'ok' "
            "ORDER BY window_end DESC LIMIT 1"
        ),
        {"h": home_id},
    )
