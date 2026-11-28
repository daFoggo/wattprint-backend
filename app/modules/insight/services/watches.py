import functools
import logging
import math
import re
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import settings
from app.database import SessionLocal
from app.modules.billing.api import current_bill, forecast_bill
from app.modules.energy.api import (
    analyzed_until,
    daily_now,
    device_breakdown,
    latest_power,
    on_w,
    runs,
    today_energy,
)
from app.modules.home.api import Device, HomeMember

from ..models import DEVICE_RUNS, WATCH_METRICS, Alert, SavingsPlan, Watch
from ..utils import WatchError

log = logging.getLogger("insight.watches")
ICT = timezone(timedelta(hours=7))
UNITS = {
    "bill_vnd": "vnd",
    "bill_kwh": "kwh",
    "forecast_vnd": "vnd",
    "today_kwh": "kwh",
    "power_w": "w",
    "device_kwh_today": "kwh",
    "device_on": "",
    "device_off": "",
    "device_run_min": "min",
    "device_power_w": "w",
}
EVERY_S = {
    "bill_vnd": 3600,
    "bill_kwh": 3600,
    "forecast_vnd": 3600,
    "today_kwh": 600,
    "power_w": 60,
    "device_kwh_today": 600,
    "sql": 600,
    **dict.fromkeys(DEVICE_RUNS, 60),
}
CYCLE = {"bill_vnd", "bill_kwh", "forecast_vnd"}  # end with the billing cycle by default
TODAY = {"today_kwh", "device_kwh_today"}  # end at local midnight by default
MAX_ACTIVE = 10  # per user per home
MAX_DAYS = 90
MAX_DAYS_REPEAT = 365  # a repeating alert is a standing rule, not a one-off
DEFAULT_DAYS = 30
BREAK_AFTER = 3  # failed checks in a row
KEEP_DAYS = 90  # ended watches are deleted after this
BATCH = 100
POWER_FRESH = timedelta(minutes=10)
RUN_KIND = {
    "device_on": "device_on",
    "device_off": "device_off",
    "device_run_min": "device_long_run",
    "device_power_w": "device_high_power",
}
# What tells of one moment or run: not for a member who sees days only.
FINE = {"power_w", *RUN_KIND}
RUN_LOOKBACK = timedelta(hours=24)  # runs are re-read whole each check; a run's start is its key
RUN_BEFORE = timedelta(hours=6)  # read this far before creation so an older run is seen as older
SAME_RUN = timedelta(minutes=15)  # NILM rewrites a run's edges while its window is a draft


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=ICT).astimezone(UTC)


@functools.cache
def _copilot_engine() -> AsyncEngine:
    # Logged in as the read-only copilot role itself: on a superuser connection a stored
    # `SELECT set_config('role', ...)` would take the superuser back.
    return create_async_engine(settings.copilot_database_url, pool_pre_ping=True, pool_size=2)


HOURLY_VIEW = re.compile(r"\b(reading|device_estimate)_1h\b", re.IGNORECASE)


async def _drop_token(token: uuid.UUID) -> None:
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_scope_token WHERE token = :t"), {"t": token})


async def run_sql(home_id: uuid.UUID, sql: str, user_id: uuid.UUID | None = None) -> Decimal | None:
    """The first column of the single row `sql` returns over this home's copilot_ro views.
    None when that value is NULL (e.g. a sum over no rows)."""
    if not settings.copilot_database_url:
        raise WatchError("custom_sql_disabled", "custom queries are not configured")
    body = sql.strip().rstrip(";")
    async with SessionLocal() as s, s.begin():
        token, detail = (  # the home's level, never finer than the watch owner may see
            await s.execute(
                text(
                    "INSERT INTO public.tb_scope_token (home_id, detail) "
                    "SELECT h.id, CASE WHEN EXISTS (SELECT 1 FROM public.tb_home_member m "
                    "WHERE m.home_id = h.id AND m.user_id = CAST(:u AS uuid) "
                    "AND m.detail = 'daily') THEN 'daily' ELSE coalesce(h.ai_detail, :d) END "
                    "FROM public.tb_home h WHERE h.id = :h "
                    "RETURNING token, detail"
                ),
                {"h": home_id, "d": settings.copilot_ai_detail_default, "u": user_id},
            )
        ).one()
    if detail != "hourly" and HOURLY_VIEW.search(body):
        # The views would answer NULL every time: say so, or the watch would never fire.
        await _drop_token(token)
        raise WatchError("needs_hourly", "this home lets Wappi see days only, not hours")
    try:
        async with _copilot_engine().connect() as c, c.begin():
            await c.execute(text("SET TRANSACTION READ ONLY"))
            await c.execute(text("SET LOCAL statement_timeout = '5s'"))
            await c.execute(
                text("SELECT set_config('app.copilot_token', :t, true)"), {"t": str(token)}
            )
            # A subquery: one statement, and at most 2 rows ever come back.
            rows = (await c.exec_driver_sql(f"SELECT * FROM ({body}) q LIMIT 2")).all()
    finally:
        await _drop_token(token)
    if len(rows) != 1 or not rows[0]:
        raise WatchError("not_one_number", f"the query returned {len(rows)} rows, not one")
    v = rows[0][0]
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int | float | Decimal):
        raise WatchError("not_one_number", "the query's first column is not a number")
    if isinstance(v, float) and not math.isfinite(v):
        raise WatchError("not_one_number", "the query returned a non-finite number")
    return Decimal(str(v))


async def measure(
    s: AsyncSession,
    home_id: uuid.UUID,
    metric: str,
    now: datetime,
    device_id: uuid.UUID | None = None,
    sql: str | None = None,
    user_id: uuid.UUID | None = None,
) -> Decimal | None:
    """The metric's value now; None while there is no figure (no reading yet, no forecast).
    Today's running kWh of a member who sees days only is as of the last 6-hour block."""
    if metric in TODAY and user_id is not None:
        detail = await s.scalar(
            select(HomeMember.detail).where(
                HomeMember.home_id == home_id, HomeMember.user_id == user_id
            )
        )
        if detail == "daily":
            now = daily_now(now)
    match metric:
        case "bill_vnd" | "bill_kwh":
            try:
                b = await current_bill(s, home_id, now)
            except LookupError as e:
                raise WatchError("no_tariff", "the home has no tariff plan") from e
            return b.amount_total if metric == "bill_vnd" else b.kwh
        case "forecast_vnd":
            try:
                f = await forecast_bill(s, home_id, now)
            except LookupError as e:
                raise WatchError("no_tariff", "the home has no tariff plan") from e
            return f.amount if f else None
        case "today_kwh":
            t = await today_energy(s, home_id, now)
            return Decimal(str(round(t.kwh, 3))) if t else None
        case "power_w":
            p = await latest_power(s, home_id, now)
            # An old minute is not "now": a stopped meter must not fire or be read back.
            fresh = p is not None and now - p.ts <= POWER_FRESH
            return Decimal(str(round(p.watts, 3))) if fresh else None
        case "device_kwh_today":
            since = _midnight(now.astimezone(ICT).date())
            if since == now:  # a daily member before 06:00: nothing counted yet
                return Decimal(0)
            for d in await device_breakdown(s, home_id, since, now):
                if d.device_id == device_id:
                    return Decimal(str(round(d.kwh, 3)))
            return Decimal(0)
        case "sql":
            return await run_sql(home_id, sql or "", user_id)
    raise WatchError("bad_metric", f"unknown metric {metric}")


def crossed(op: str, value: Decimal, threshold: Decimal) -> bool:
    return value > threshold if op == "gt" else value < threshold


async def _default_end(s: AsyncSession, home_id: uuid.UUID, metric: str, now: datetime):
    if metric in CYCLE:
        b = await current_bill(s, home_id, now)
        return _midnight(b.period_end + timedelta(days=1))
    if metric in TODAY:
        return _midnight(now.astimezone(ICT).date() + timedelta(days=1))
    return now + timedelta(days=DEFAULT_DAYS)


async def create_watch(
    s: AsyncSession,
    user_id: uuid.UUID,
    home_id: uuid.UUID,
    *,
    metric: str,
    op: str,
    threshold: float,
    label: str,
    now: datetime,
    utterance: str = "",
    unit: str | None = None,
    device_id: uuid.UUID | None = None,
    sql: str | None = None,
    ends_on: date | None = None,
    repeat: bool = False,
) -> tuple[Watch, Decimal | None]:
    """Check the request, measure the metric once (a custom query must give one number) and store
    the watch. Returns it with the value now. The caller commits."""
    if metric not in WATCH_METRICS:
        raise WatchError("bad_metric", f"unknown metric {metric}")
    if op not in ("gt", "lt"):
        raise WatchError("bad_op", "op is gt or lt")
    if not math.isfinite(threshold) or abs(threshold) >= 1e11:
        raise WatchError("bad_threshold", "the threshold is not a usable number")
    if (metric == "sql") != bool(sql):
        raise WatchError("bad_metric", "a sql watch needs its query, and only it")
    fine = metric in FINE or (metric == "sql" and HOURLY_VIEW.search(sql or ""))
    if (
        fine
        and await s.scalar(
            select(HomeMember.detail).where(
                HomeMember.home_id == home_id, HomeMember.user_id == user_id
            )
        )
        == "daily"
    ):
        raise WatchError("needs_hourly", "you see this home by the day, not by the moment")
    if metric.startswith("device_"):
        kind = await s.scalar(
            select(Device.device_type_code).where(Device.id == device_id, Device.home_id == home_id)
        )
        if kind is None:
            raise WatchError("no_device", "no such device in this home")
        if kind == "other" and metric in DEVICE_RUNS:
            raise WatchError("bad_device", "the unknown remainder has no runs to tell about")
    else:
        device_id = None
    active = await s.scalar(
        select(func.count()).where(
            Watch.user_id == user_id, Watch.home_id == home_id, Watch.status == "active"
        )
    )
    if active >= MAX_ACTIVE:
        raise WatchError("too_many", f"at most {MAX_ACTIVE} watches at a time; cancel one first")

    runs = metric in DEVICE_RUNS
    repeat = repeat or runs  # a device run alert is always once per run
    if metric in ("device_on", "device_off"):
        op, threshold = "gt", 0.0
    # A per-run alert has no figure to compare now; it judges each run as it comes.
    value = None if runs else await measure(s, home_id, metric, now, device_id, sql, user_id)
    limit = Decimal(str(threshold))
    if value is not None and crossed(op, value, limit) and not repeat:
        raise WatchError("already_crossed", "the value is already past the threshold", value)
    longest = MAX_DAYS_REPEAT if repeat else MAX_DAYS
    ends_at = (
        now + timedelta(days=MAX_DAYS_REPEAT)
        if repeat
        else await _default_end(s, home_id, metric, now)
    )
    if ends_on is not None:
        ends_at = _midnight(ends_on + timedelta(days=1))
    ends_at = min(ends_at, now + timedelta(days=longest))
    if ends_at <= now:
        raise WatchError("ends_in_past", "the end date has already passed")
    every = EVERY_S[metric]
    w = Watch(
        user_id=user_id,
        home_id=home_id,
        device_id=device_id,
        metric=metric,
        label=label.strip()[:200] or metric,
        sql_text=sql if metric == "sql" else None,
        op=op,
        threshold=limit,
        unit=UNITS.get(metric) or (unit or "")[:16],
        every_s=every,
        repeat=repeat,
        ends_at=ends_at,
        next_check_at=now + timedelta(seconds=every),
        last_value=value,
        last_checked_at=now,
        utterance=utterance[:2000],
    )
    s.add(w)
    await s.flush()
    return w, value


async def list_watches(s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID) -> list[Watch]:
    """The user's watches in this home: active first, then newest first."""
    return list(
        await s.scalars(
            select(Watch)
            .where(Watch.user_id == user_id, Watch.home_id == home_id)
            .order_by(case((Watch.status == "active", 0), else_=1), Watch.created_at.desc())
            .limit(50)
        )
    )


async def cancel_watch(
    s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID, watch_id: uuid.UUID
) -> bool:
    """Active or broken → cancelled; False when the user has no such watch here. Idempotent."""
    found = await s.scalar(
        select(Watch.id).where(
            Watch.id == watch_id, Watch.user_id == user_id, Watch.home_id == home_id
        )
    )
    if found is None:
        return False
    await s.execute(
        update(Watch)
        .where(Watch.id == watch_id, Watch.status.in_(("active", "broken")))
        .values(status="cancelled")
    )
    return True


def run_alerts(
    metric: str,
    threshold: float,
    minutes: list[tuple[datetime, float, float, float]],
    on_watts: float,
    created_at: datetime,
    now: datetime,
    last_at: datetime | None = None,
    window_start: datetime | None = None,
) -> list[tuple[datetime, float | None]]:
    """The device runs a per-run alert fires for, as (run start, figure): each run that started
    after the watch was set and turned on, ended, ran past `threshold` minutes or peaked past it.
    `now` is how far NILM has analysed. A run starting where reading began (`window_start`) is
    an older run cut by the window, and one within SAME_RUN of the last run told (`last_at`) is that
    run with its edge rewritten."""
    out: list[tuple[datetime, float | None]] = []
    for c in runs([(b, w, wh) for b, w, wh, _ in minutes], on_watts, now):
        # the first bucket read is the next whole minute after `window_start`
        if c.start < created_at or (
            window_start is not None and c.start < window_start + timedelta(minutes=1)
        ):
            continue
        if last_at is not None and c.start <= last_at + SAME_RUN:
            continue
        if metric == "device_on":
            out.append((c.start, None))
        elif metric == "device_off" and c.end is not None:
            out.append((c.start, None))
        elif metric == "device_run_min":
            ran = ((c.end or now) - c.start).total_seconds() / 60
            if ran > threshold:
                out.append((c.start, round(ran, 1)))
        elif metric == "device_power_w":
            until = c.end or now + timedelta(minutes=1)
            peak = max(m for b, _, _, m in minutes if c.start <= b < until)
            if peak > threshold:
                out.append((c.start, float(peak)))
    return out


async def _device_runs(s: AsyncSession, w: Watch, now: datetime):
    """The device's name and the runs this watch fires for, from NILM's per-minute estimates."""
    row = (
        await s.execute(
            text(
                "SELECT s.series_id, d.device_type_code AS type, d.name FROM public.tb_device d "
                "JOIN public.tb_series s ON s.device_id = d.id AND s.kind = 'device' "
                "AND s.metric = 'power_w' WHERE d.id = :d"
            ),
            {"d": w.device_id},
        )
    ).first()
    if row is None or row.type == "other":  # the unknown remainder is on all the time
        return "", []
    # As of what NILM has analysed: a minute it has not reached yet is not "off".
    now = min(now, await analyzed_until(s, w.home_id) or now)
    since = max(w.created_at - RUN_BEFORE, now - RUN_LOOKBACK)
    minutes = [
        (r.bucket, float(r.avg_w), float(r.energy_wh), float(r.max_w))
        for r in await s.execute(
            text(
                "SELECT bucket, avg_w, energy_wh, max_w FROM public.device_estimate_1m "
                "WHERE series_id = :s AND bucket >= :lo AND bucket <= :now ORDER BY bucket"
            ),
            {"s": row.series_id, "lo": since, "now": now},
        )
    ]
    told = await s.scalar(
        select(func.max(Alert.payload["at"].astext)).where(
            Alert.home_id == w.home_id, Alert.dedup_key.like(f"watch:{w.id}:%")
        )
    )
    last_at = datetime.fromisoformat(told) if told else None
    hits = run_alerts(
        w.metric, float(w.threshold), minutes, on_w(row.type), w.created_at, now, last_at, since
    )
    return row.name, hits


async def _period(s: AsyncSession, w: Watch, now: datetime) -> tuple[str, datetime]:
    """A repeating watch's current period (its alert key) and when the next one starts."""
    if w.metric in CYCLE:
        b = await current_bill(s, w.home_id, now)
        return str(b.period_start), _midnight(b.period_end + timedelta(days=1))
    if w.metric == "power_w":
        hour = now.replace(minute=0, second=0, microsecond=0)
        return hour.isoformat(), hour + timedelta(hours=1)
    today = now.astimezone(ICT).date()
    return str(today), _midnight(today + timedelta(days=1))


async def _alert(
    s: AsyncSession,
    w: Watch,
    kind: str,
    now: datetime,
    key: str | None = None,
    extra: dict | None = None,
) -> None:
    payload = {
        "watch_id": str(w.id),
        "label": w.label,
        "op": w.op,
        "threshold": float(w.threshold),
        "unit": w.unit,
        "repeat": w.repeat,
    }
    if w.last_value is not None:
        payload["value"] = float(w.last_value)
    payload.update({k: v for k, v in (extra or {}).items() if v is not None})
    await s.execute(
        insert(Alert)
        .values(
            home_id=w.home_id,
            kind=kind,
            severity="warning",
            ts=now,
            payload=payload,
            # one alert per watch, or per period / device run for a repeating one
            dedup_key=f"watch:{w.id}" if key is None else f"watch:{w.id}:{key}",
        )
        .on_conflict_do_nothing()
    )


async def _check(s: AsyncSession, w: Watch, now: datetime) -> None:
    if now >= w.ends_at:
        w.status = "expired"
        return
    try:
        async with s.begin_nested():
            if w.metric in DEVICE_RUNS:
                device, hits = await _device_runs(s, w, now)
            else:
                value = await measure(
                    s, w.home_id, w.metric, now, w.device_id, w.sql_text, w.user_id
                )
    except Exception:
        log.warning("watch %s check failed", w.id, exc_info=True)
        w.fails += 1
        w.next_check_at = now + timedelta(seconds=w.every_s)
        if w.fails >= BREAK_AFTER:
            w.status = "broken"
            await _alert(s, w, "watch_broken", now)
        return
    w.fails = 0
    w.last_checked_at = now
    w.next_check_at = now + timedelta(seconds=w.every_s)
    if w.metric in DEVICE_RUNS:
        for at, figure in hits:
            await _alert(
                s,
                w,
                RUN_KIND[w.metric],
                now,
                key=at.isoformat(),
                extra={"device": device, "at": at.isoformat(), "value": figure},
            )
            w.fired_at = now
        return
    if value is None:
        return
    w.last_value = value
    if not crossed(w.op, value, w.threshold):
        return
    w.fired_at = now
    if w.repeat:
        key, next_period = await _period(s, w, now)
        await _alert(s, w, "watch_hit", now, key=key)
        w.next_check_at = next_period
    else:
        w.status = "fired"
        await _alert(s, w, "watch_hit", now)


async def check_due(now: datetime) -> int:
    """Check every active watch whose time has come, in batches. Rows are claimed with
    SKIP LOCKED, so workers running side by side never check the same watch. Returns how many."""
    done = 0
    while True:
        async with SessionLocal() as s, s.begin():
            batch = list(
                await s.scalars(
                    select(Watch)
                    .where(Watch.status == "active", Watch.next_check_at <= now)
                    .order_by(Watch.next_check_at)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)
                )
            )
            for w in batch:
                await _check(s, w, now)
        done += len(batch)
        if len(batch) < BATCH:
            return done


async def prune_watches(s: AsyncSession, now: datetime) -> None:
    """Ended watches go KEEP_DAYS after they last changed."""
    await s.execute(
        text(
            "DELETE FROM public.tb_watch WHERE status <> 'active' "
            "AND coalesce(fired_at, last_checked_at, created_at) < :t"
        ),
        {"t": now - timedelta(days=KEEP_DAYS)},
    )


async def forget_fine_watches(s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID) -> None:
    """Their alerts on the moment (and every custom query, which may read hours) are deleted."""
    await s.execute(
        delete(Watch).where(
            Watch.user_id == user_id,
            Watch.home_id == home_id,
            Watch.metric.in_((*FINE, "sql")),
        )
    )


async def forget_member(s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID) -> None:
    """The alerts and savings plans of someone leaving the home, in the caller's transaction."""
    for model in (Watch, SavingsPlan):
        await s.execute(delete(model).where(model.user_id == user_id, model.home_id == home_id))
