import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import exists, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.billing.api import current_bill, forecast_bill
from app.modules.energy.api import analyzed_until, weather_inputs
from app.modules.expect.api import (
    ExpectModel,
    activity_ratio,
    device_actual,
    device_band,
    expected,
    hourly_actual,
)
from app.modules.ops.api import scenarios_between

from ..models import Alert
from .cycles import refresh_cycles
from .device_signals import (
    MIN_DAYS,
    MIN_RUNS,
    TEMP_C,
    Run,
    daily_excess,
    denser_cycling,
    long_run,
    odd_hour,
    outside_events,
    peers_of,
)
from .feedback import sensitivity

ICT = timezone(timedelta(hours=7))
BASE_DAYS = 28  # the usual: the 28 days (or nights) before the recent ones
RECENT_DAYS = 3
STANDBY_RATIO, STANDBY_PLUS_W = 1.3, 50.0
NIGHT_END_H = 5  # standby is read 00:00-05:00, when little is switched on by hand
UNEXPLAINED_PLUS_W = 300.0
UNEXPLAINED_MIN = 30
TIER_DAYS = 3
USAGE = "usage_anomaly"
BUSY = 1.5  # activity this many times the routine: guests or a day at home, said so in the alert


@dataclass
class Finding:
    kind: str
    dedup_key: str
    severity: str
    payload: dict[str, float]
    device_id: uuid.UUID | None = None


# Each detector returns what holds now, or None when the data cannot tell (then its open alerts
# stay as they are instead of being resolved for lack of data).


async def _standby_high(s: AsyncSession, home_id: uuid.UUID, now: datetime):
    last_night = (now.astimezone(ICT) - timedelta(hours=NIGHT_END_H)).date()
    first_recent = last_night - timedelta(days=RECENT_DAYS - 1)

    def midnight(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=ICT).astimezone(UTC)

    r = (
        await s.execute(
            text(
                "WITH m AS (SELECT r.bucket >= :split AS recent, sum(r.avg_w) AS w "
                "FROM public.reading_1m r JOIN public.tb_series s USING (series_id) "
                "WHERE s.home_id = :h AND s.kind = 'main' AND s.metric = 'power_w' "
                "AND r.bucket >= :lo AND r.bucket < :hi "
                "AND extract(hour FROM r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh') < :end_h "
                "GROUP BY r.bucket) "
                "SELECT percentile_cont(0.05) WITHIN GROUP (ORDER BY w) FILTER (WHERE recent) AS n,"
                " count(*) FILTER (WHERE recent) AS n_min, "
                "percentile_cont(0.05) WITHIN GROUP (ORDER BY w) FILTER (WHERE NOT recent) AS u, "
                "count(*) FILTER (WHERE NOT recent) AS u_min FROM m"
            ),
            {
                "h": home_id,
                "split": midnight(first_recent),
                "lo": midnight(first_recent - timedelta(days=BASE_DAYS)),
                "hi": midnight(last_night + timedelta(days=1)),
                "end_h": NIGHT_END_H,
            },
        )
    ).one()
    night = NIGHT_END_H * 60
    if (
        r.n_min < 0.8 * RECENT_DAYS * night or r.u_min < 0.8 * 7 * night
    ):  # a week of nights at least
        return None
    if r.n > STANDBY_RATIO * r.u and r.n - r.u > STANDBY_PLUS_W:
        return [
            Finding(
                "standby_high",
                "standby_high",
                "info",
                {"usual_w": round(r.u), "recent_w": round(r.n), "nights": RECENT_DAYS},
            )
        ]
    return []


async def _unexplained_load(s: AsyncSession, home_id: uuid.UUID, until: datetime):
    other = await s.scalar(
        text(
            "SELECT s.series_id FROM public.tb_series s "
            "JOIN public.tb_device d ON d.id = s.device_id "
            "WHERE s.home_id = :h AND s.kind = 'device' AND d.device_type_code = 'other' LIMIT 1"
        ),
        {"h": home_id},
    )
    if other is None:
        return None
    recent_lo = until - timedelta(hours=6)
    base = (
        await s.execute(
            text(
                "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY avg_w) AS p95, count(*) AS n "
                "FROM public.device_estimate_1m WHERE series_id = :s AND bucket >= :lo "
                "AND bucket < :hi"
            ),
            {"s": other, "lo": recent_lo - timedelta(days=BASE_DAYS), "hi": recent_lo},
        )
    ).one()
    if base.n < 0.8 * 7 * 1440:
        return None
    bar = float(base.p95) + UNEXPLAINED_PLUS_W
    minutes = (
        await s.execute(
            text(
                "SELECT bucket, avg_w FROM public.device_estimate_1m WHERE series_id = :s "
                "AND bucket >= :lo AND bucket < :hi ORDER BY bucket DESC"
            ),
            {"s": other, "lo": recent_lo, "hi": until},
        )
    ).all()
    streak, watts, expect = 0, 0.0, None
    for m in minutes:  # back from the newest minute, while it stays over the bar without a gap
        if float(m.avg_w) <= bar or (expect is not None and m.bucket != expect):
            break
        streak, watts, expect = streak + 1, watts + float(m.avg_w), m.bucket - timedelta(minutes=1)
    if streak < UNEXPLAINED_MIN:
        return []
    return [
        Finding(
            "unexplained_load",
            "unexplained_load",
            "warning",
            {"watts": round(watts / streak), "usual_w": round(base.p95), "minutes": streak},
        )
    ]


async def _tier_near(s: AsyncSession, home_id: uuid.UUID, now: datetime):
    try:
        bill = await current_bill(s, home_id, now)
        f = await forecast_bill(s, home_id, now)
    except LookupError:  # no tariff: nothing to warn about
        return []
    today = now.astimezone(ICT).date()
    near = {}
    if bill.tier_no >= 2:  # already in a higher tier this cycle
        t = next(t for t in bill.tiers if t.tier_no == bill.tier_no)
        near[t.tier_no] = (t.from_kwh, t.price_per_kwh, 0)
    if f and f.next and (f.next.on - today).days <= TIER_DAYS:
        n = f.next
        near[n.tier_no] = (n.from_kwh, n.price_per_kwh, max(0, (n.on - today).days))
    return [
        Finding(
            "tier_near",
            f"tier_near:{bill.period_start}:{tier}",
            "info",
            {"tier_no": tier, "from_kwh": float(k), "price_per_kwh": float(p), "days": d},
        )
        for tier, (k, p, d) in near.items()
    ]


def judge(
    actual: list[float],
    p50: list[float],
    p95: list[float],
    price: float,
    min_vnd: float,
    factor: float,
) -> dict[str, float] | None:
    """A window's usage against the model's expectation for its context: it counts when every
    hour is known, its total passes the expected total plus `factor` times the P95 band, and the
    excess is worth at least `min_vnd`."""
    if not actual or any(math.isnan(a) for a in actual):
        return None
    act, e50, e95 = sum(actual), sum(p50), sum(p95)
    excess = act - e50
    if act <= e50 + factor * (e95 - e50) or excess * price < min_vnd:
        return None
    return {
        "excess_kwh": round(excess, 1),
        "excess_vnd": float(round(excess * price)),
        "expected_kwh": round(e50, 1),
        "actual_kwh": round(act, 1),
    }


def rule_kinds(has_model: bool) -> tuple[str, ...]:
    """With an expected-usage model, the in-context anomaly replaces the fixed +300 W rule."""
    return ("longer_than_usual", "standby_high", "tier_near") + (
        (USAGE,) if has_model else ("unexplained_load",)
    )


async def _top_device(s: AsyncSession, home_id: uuid.UUID, lo: datetime, hi: datetime):
    """The NILM device that used the most over its own usual for these hours (the same hours of
    the 4 weeks before); None when none used more."""
    row = (
        await s.execute(
            text(
                "WITH win AS (SELECT x.device_id, sum(e.energy_wh) / 1000 AS kwh "
                "  FROM public.device_estimate_1h e JOIN public.tb_series x USING (series_id) "
                "  WHERE x.home_id = :h AND x.kind = 'device' "
                "  AND e.bucket >= :lo AND e.bucket < :hi "
                "  GROUP BY 1), "
                "usual AS (SELECT x.device_id, sum(e.energy_wh) / 1000 / 4 AS kwh "
                "  FROM generate_series(1, 4) k, public.device_estimate_1h e "
                "  JOIN public.tb_series x USING (series_id) "
                "  WHERE x.home_id = :h AND x.kind = 'device' "
                "  AND e.bucket >= :lo - k * interval '7 days' "
                "  AND e.bucket < :hi - k * interval '7 days' GROUP BY 1) "
                "SELECT win.device_id, win.kwh - coalesce(usual.kwh, 0) AS more "
                "FROM win LEFT JOIN usual USING (device_id) ORDER BY more DESC LIMIT 1"
            ),
            {"h": home_id, "lo": lo, "hi": hi},
        )
    ).first()
    return row.device_id if row is not None and row.more > 0 else None


async def _usage_anomaly(s: AsyncSession, home_id: uuid.UUID, now: datetime):
    """Today's usage, or the last three hours', past what the model expects in this context
    (weather, calendar, routine) and worth the money; None when there is no expectation."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    local = now.astimezone(ICT)
    midnight = datetime(local.year, local.month, local.day, tzinfo=ICT).astimezone(UTC)
    frame = await expected(s, home_id, midnight, hour)
    if frame.empty:
        return None
    try:
        bill = await current_bill(s, home_id, now)
    except LookupError:  # no tariff: no money to weigh it by
        return None
    if bill.kwh <= 0:
        return None
    price = float(bill.amount_total / bill.kwh)
    factor = await sensitivity(s, home_id, USAGE)
    actual = await hourly_actual(s, home_id, midnight, hour)
    best = None
    for lo, min_vnd in (
        (hour - timedelta(hours=3), settings.anomaly_min_vnd_3h),
        (midnight, settings.anomaly_min_vnd_day),
    ):
        win = frame[frame.index >= lo]
        if win.empty:
            continue
        got = judge(
            actual.reindex(win.index).tolist(),
            win["p50"].tolist(),
            win["p95"].tolist(),
            price,
            min_vnd,
            factor,
        )
        if got and (best is None or got["excess_vnd"] > best[0]["excess_vnd"]):
            best = (got, lo, win)
    if best is None:
        return []
    got, lo, win = best
    ratio = await activity_ratio(s, home_id, lo, hour)
    payload = {
        **got,
        "hours": len(win),
        "weather_kwh": round(float(win["c_weather"].sum()), 1),
        "activity_ratio": round(ratio, 2),
        "start": lo.isoformat(),
    }
    return [
        Finding(
            USAGE,
            f"{USAGE}:{local.date().isoformat()}",
            "info" if ratio >= BUSY else "warning",
            payload,
            await _top_device(s, home_id, lo, hour),
        )
    ]


async def settle_usage(
    s: AsyncSession, home_id: uuid.UUID, found: list[Finding], now: datetime
) -> None:
    """Raise or refresh today's in-context anomaly; one per local day: an alert of an earlier day
    is resolved, today's stays (acknowledged or not) until the day ends."""
    for f in found:
        await _upsert(s, home_id, f, now)
    today = f"{USAGE}:{now.astimezone(ICT).date().isoformat()}"
    await s.execute(
        update(Alert)
        .where(
            Alert.home_id == home_id,
            Alert.kind == USAGE,
            Alert.status != "resolved",
            Alert.dedup_key < today,
        )
        .values(status="resolved", resolved_at=now)
    )


async def _upsert(s: AsyncSession, home_id: uuid.UUID, f: Finding, now: datetime) -> None:
    stmt = insert(Alert).values(
        home_id=home_id,
        device_id=f.device_id,
        kind=f.kind,
        severity=f.severity,
        ts=now,
        payload=f.payload,
        dedup_key=f.dedup_key,
    )
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=["home_id", "dedup_key"],
            # A literal: a bound parameter stops Postgres matching the partial index once it
            # switches the prepared statement to a generic plan (after five runs).
            index_where=text("status <> 'resolved'"),
            set_={"payload": stmt.excluded.payload, "severity": stmt.excluded.severity},
            # A weaker finding never rewrites the shown one (0 when a kind has no money).
            where=text(
                "coalesce((excluded.payload->>'excess_vnd')::float, 0) >= "
                "coalesce((public.tb_alert.payload->>'excess_vnd')::float, 0)"
            ),
        )
    )


DEVICE = "device_anomaly"
CYCLING = ("fridge", "fridge_freezer", "freezer")
HISTORY = timedelta(days=60)


async def _avg_price(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> float | None:
    """What a kWh costs the home on average this cycle (VAT included); None without a tariff."""
    try:
        bill = await current_bill(s, home_id, now)
    except LookupError:
        return None
    return float(bill.amount_total / bill.kwh) if bill.kwh > 0 else None


async def _device_runs(s: AsyncSession, device_id: uuid.UUID, lo: datetime, until: datetime):
    return (
        await s.execute(
            text(
                "SELECT start_ts, end_ts, energy_wh FROM public.tb_device_cycle "
                "WHERE device_id = :d AND start_ts >= :lo AND end_ts <= :until ORDER BY start_ts"
            ),
            {"d": device_id, "lo": lo, "until": until},
        )
    ).all()


def _to_run(r, temps) -> Run:
    local = r.start_ts.astimezone(ICT)
    temp = temps.get(pd.Timestamp(r.start_ts).floor("h"))
    return Run(
        minutes=(r.end_ts - r.start_ts).total_seconds() / 60,
        kwh=float(r.energy_wh) / 1000,
        start_hour=local.hour,
        temp_c=None if temp is None or pd.isna(temp) else float(temp),
        day=local.toordinal(),
    )


def same_temperature(old: dict[int, tuple[float, float | None]], temp_now: float | None):
    """D4's usual: the mean on-time share of the old days (28–56 days back) whose mean
    temperature was within ±3 °C of the last 3 days'; None when no such day."""
    if temp_now is None:
        return None
    alike = [share for share, t in old.values() if t is not None and abs(t - temp_now) <= TEMP_C]
    return sum(alike) / len(alike) if alike else None


async def _device_anomalies(s: AsyncSession, home_id: uuid.UUID, until: datetime, now: datetime):
    """Per device: its runs that ended today and today's kWh against its own past in the same
    context (D1–D4, spec docs/work/2026-11-23-device-ai §2). Only what NILM has analysed counts;
    each run is judged once, on the local day it ended."""
    price = await _avg_price(s, home_id, now)
    if price is None:
        return None
    devices = (
        await s.execute(
            text(
                "SELECT id, device_type_code AS type FROM public.tb_device "
                "WHERE home_id = :h AND device_type_code <> 'other' AND deleted_at IS NULL"
            ),
            {"h": home_id},
        )
    ).all()
    local = until.astimezone(ICT)
    midnight = datetime(local.year, local.month, local.day, tzinfo=ICT).astimezone(UTC)
    hour = until.replace(minute=0, second=0, microsecond=0)  # D1 on whole analysed hours
    temps = (await weather_inputs(s, home_id, until - HISTORY, until, now))["temp_c"]
    day_temp = temps.groupby(temps.index.tz_convert(ICT).date).mean()
    events = [
        (sc.starts_at, sc.ends_at)
        for sc in await scenarios_between(s, home_id, until - HISTORY, until)
        if not sc.train
    ]
    out = []
    for d in devices:
        rows = await _device_runs(s, d.id, until - HISTORY, until)
        all_runs = [(r, _to_run(r, temps)) for r in rows]
        recent = [(r, x) for r, x in all_runs if r.end_ts >= midnight]
        # D2/D3 history leaves out demo events (a staged run is judged, never a peer).
        past = [_to_run(r, temps) for r in outside_events(rows, events) if r.end_ts < midnight]
        days = (past[-1].day - past[0].day + 1) if past else 0
        enough = days >= MIN_DAYS and len(past) >= MIN_RUNS  # D2 and D3 (spec §2.1)
        factor = {
            sig: await sensitivity(s, home_id, DEVICE, d.id, sig)
            for sig in ("long_run", "odd_hour", "denser", "daily")
        }
        found = []
        for r, x in recent if enough else []:
            if got := long_run(x, peers_of(x, past), price, factor["long_run"]):
                found.append({**got, "at": r.start_ts.isoformat()})
            at_hour = len({p.day for p in past if p.start_hour == x.start_hour})
            if got := odd_hour(x.start_hour, at_hour, days, len(past), factor["odd_hour"]):
                found.append({**got, "at": r.start_ts.isoformat()})
        if d.type in CYCLING and past:
            share: dict[int, float] = {}
            for _, x in all_runs:
                share[x.day] = share.get(x.day, 0.0) + x.minutes / 1440
            today = local.toordinal()
            last3 = [share.get(today - k, 0.0) for k in (3, 2, 1)]
            recent_t = [day_temp.get(date.fromordinal(today - k)) for k in (3, 2, 1)]
            recent_t = [t for t in recent_t if t is not None and not pd.isna(t)]
            old = {
                k: (share[k], day_temp.get(date.fromordinal(k)))
                for k in share
                if 28 <= today - k <= 56
            }
            usual = same_temperature(old, sum(recent_t) / len(recent_t) if recent_t else None)
            daily = sum(x.kwh for x in past) / max(days, 1)
            if usual and (got := denser_cycling(last3, usual, daily, price, factor["denser"])):
                found.append(got)
        band = await device_band(s, home_id, d.id, midnight, hour, now) if hour > midnight else None
        if band is not None and len(band):
            actual = await device_actual(s, d.id, midnight, hour)
            known = actual.reindex(band.index).notna()
            if known.all():
                if got := daily_excess(
                    float(actual.sum()),
                    float(band["p50"].sum()),
                    float(band["p95"].sum()),
                    price,
                    factor["daily"],
                ):
                    found.append(got)
        if found:
            best = max(found, key=lambda g: g.get("excess_vnd", 0.0))
            out.append(
                Finding(
                    DEVICE, f"{DEVICE}:{d.id}:{local.date().isoformat()}", "warning", best, d.id
                )
            )
    return out


async def settle_devices(
    s: AsyncSession,
    home_id: uuid.UUID,
    found: list[Finding],
    until: datetime,
    now: datetime | None = None,
) -> None:
    """One device anomaly per device per local day of what NILM has analysed (`until`): that
    day's stay, earlier days resolve. Using `until`, not the clock, keeps a lagging NILM from
    raising and resolving the same alert past midnight."""
    now = now or until
    for f in found:
        await _upsert(s, home_id, f, now)
    day = until.astimezone(ICT).date().isoformat()
    await s.execute(
        update(Alert)
        .where(
            Alert.home_id == home_id,
            Alert.kind == DEVICE,
            Alert.status != "resolved",
            ~Alert.dedup_key.like(f"%:{day}"),
        )
        .values(status="resolved", resolved_at=now)
    )


async def _nothing() -> list:
    return []


async def detect(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> None:
    """Raise what holds now, refresh the figures of what is already open, resolve what no longer
    holds. Device checks are as of what NILM has analysed, not the wall clock."""
    until = await analyzed_until(s, home_id)
    if until is not None:
        await refresh_cycles(s, home_id, until)
    has_model = bool(
        await s.scalar(
            select(
                exists().where(
                    ExpectModel.home_id == home_id,
                    ExpectModel.device_id.is_(None),
                    ExpectModel.active,
                )
            )
        )
    )
    kinds = rule_kinds(has_model)
    if USAGE in kinds:
        found = await _usage_anomaly(s, home_id, now)
        await settle_usage(s, home_id, found or [], now)
    if until is not None:
        found = await _device_anomalies(s, home_id, until, now)
        if found is not None:
            await settle_devices(s, home_id, found, until, now)
    checks = {
        # Replaced by device_anomaly (long runs and denser cycling): its open alerts resolve.
        "longer_than_usual": _nothing,
        "standby_high": lambda: _standby_high(s, home_id, now),
        # With a model the old rule finds nothing, so its open alerts resolve.
        "unexplained_load": lambda: (
            _unexplained_load(s, home_id, until)
            if "unexplained_load" in kinds and until
            else (_nothing() if "unexplained_load" not in kinds else None)
        ),
        "tier_near": lambda: _tier_near(s, home_id, now),
    }
    for kind, check in checks.items():
        pending = check()
        found = await pending if pending is not None else None
        if found is None:
            continue
        for f in found:
            await _upsert(s, home_id, f, now)
        await s.execute(
            update(Alert)
            .where(
                Alert.home_id == home_id,
                Alert.kind == kind,
                Alert.status != "resolved",
                Alert.dedup_key.not_in([f.dedup_key for f in found]),
            )
            .values(status="resolved", resolved_at=now)
        )
