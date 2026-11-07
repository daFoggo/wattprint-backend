"""Appliance cycles and the five behaviour patterns ("motifs"), as SQL on the app login.

Every query filters by the run's home. Instances are upserted into insight.motif_instance with
their facts; rules (rules.py) read them back through copilot_ro.motif_instance.
"""

import datetime as dt
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools.catalog import PLUG_COVERS
from ..tools.sql_builder import local_midnight

# motif -> fact -> unit ("" = a label such as a date; "x" = a ratio). Rules compare numeric facts.
FACTS: dict[str, dict[str, str]] = {
    "night_baseline": {"night": "", "min_w": "W", "median_w": "W", "excess_w": "W", "ratio": "x"},
    "day_above_usual": {"day": "", "kwh": "kWh", "median_kwh": "kWh", "excess_kwh": "kWh",
                        "ratio": "x"},
    "repeat_use": {"cycles": "cycles", "window_min": "min", "kwh": "kWh"},
    "long_run": {"minutes": "min", "limit_min": "min", "kwh": "kWh"},
    "tier_crossing": {"month_kwh": "kWh", "avg_daily_kwh": "kWh", "days_left": "days",
                      "projected_kwh": "kWh", "tier": "tier", "tier_from_kwh": "kWh",
                      "cut_kwh_per_day": "kWh"},
}
DEVICE_MOTIFS = {"repeat_use", "long_run"}
WINDOW_DAYS = 7
NIGHT_HOURS = 5  # 00:00-05:00 local
# Night and day instances are observations (one per night / day, with its ratio to the window's
# median); "unusually high" is a rule over them (rules.SHARED_RULES), so household rules can count
# nights too ("at least 3 nights above 300 W").
REPEAT = {"kettle": (3, 30)}  # device type -> (k cycles, within minutes)
LONG_RUN_MIN = {"kettle": 10, "microwave": 30, "washing_machine": 180, "dishwasher": 240,
                "tumble_dryer": 150, "washer_dryer": 240}
ON_MIN_W, ON_SHARE, MERGE_GAP_MIN = 20, 0.1, 3


def window(today: dt.date, tz: str) -> tuple[dt.datetime, dt.datetime]:
    """The last WINDOW_DAYS local days before today, as UTC bounds."""
    return (local_midnight(today - dt.timedelta(days=WINDOW_DAYS), tz), local_midnight(today, tz))


CYCLES_SQL = """
WITH on_min AS (
    SELECT s.device_id, r.bucket AS ts, r.avg_w, r.max_w
    FROM energy.{view} r
    JOIN energy.series s ON s.series_id = r.series_id
    JOIN core.device d ON d.id = s.device_id AND d.home_id = s.home_id
    JOIN catalog.device_type t ON t.code = d.device_type_code
    WHERE s.home_id = :h AND s.kind = :kind AND s.device_id = ANY(:devices)
      AND r.bucket >= :lo AND r.bucket < :hi
      AND r.avg_w >= greatest(:on_w, :share * coalesce(t.typical_watts, 0))
),
marked AS (
    SELECT *, CASE WHEN ts - lag(ts) OVER w <= make_interval(mins => :gap) THEN 0 ELSE 1 END
              AS new_run
    FROM on_min WINDOW w AS (PARTITION BY device_id ORDER BY ts)
),
runs AS (
    SELECT *, sum(new_run) OVER (PARTITION BY device_id ORDER BY ts) AS run FROM marked
)
INSERT INTO insight.device_cycle (home_id, device_id, start_ts, end_ts, energy_wh, peak_w)
SELECT :h, device_id, min(ts), max(ts) + interval '1 minute', sum(avg_w) / 60, max(max_w)
FROM runs GROUP BY device_id, run
ON CONFLICT (device_id, start_ts) DO UPDATE
SET end_ts = excluded.end_ts, energy_wh = excluded.energy_wh, peak_w = excluded.peak_w
"""


async def derive_cycles(session: AsyncSession, home_id: uuid.UUID, lo: dt.datetime,
                        hi: dt.datetime) -> int:
    """On/off cycles per device: the plug when it covers the window, else the NILM estimate."""
    minutes = int((hi - lo).total_seconds() // 60)
    rows = (await session.execute(text("""
        SELECT d.id AS device_id,
               coalesce((SELECT sum(r.covered_minutes) FROM energy.reading_1d r
                         JOIN energy.series s ON s.series_id = r.series_id
                         WHERE s.device_id = d.id AND s.kind = 'plug'
                           AND r.bucket >= :lo AND r.bucket < :hi), 0) AS plug_minutes,
               EXISTS (SELECT 1 FROM energy.series s
                       WHERE s.device_id = d.id AND s.kind = 'device') AS estimated
        FROM core.device d WHERE d.home_id = :h AND d.deleted_at IS NULL
    """), {"h": home_id, "lo": lo, "hi": hi})).all()
    by_kind: dict[str, list[uuid.UUID]] = {"plug": [], "device": []}
    for r in rows:
        if r.plug_minutes >= PLUG_COVERS * minutes:
            by_kind["plug"].append(r.device_id)
        elif r.estimated:
            by_kind["device"].append(r.device_id)
    total = 0
    for kind, view in (("plug", "reading_1m"), ("device", "device_estimate_1m")):
        if not by_kind[kind]:
            continue
        res = await session.execute(
            text(CYCLES_SQL.format(view=view)),
            {"h": home_id, "kind": kind, "devices": by_kind[kind], "lo": lo, "hi": hi,
             "on_w": ON_MIN_W, "share": ON_SHARE, "gap": MERGE_GAP_MIN},
        )
        total += res.rowcount or 0
    await session.commit()
    return total


UPSERT = text("""
INSERT INTO insight.motif_instance (home_id, motif, device_id, start_ts, end_ts, facts, kwh)
VALUES (:h, :motif, :device, :start, :end, CAST(:facts AS jsonb), :kwh)
ON CONFLICT ON CONSTRAINT uq_motif_instance_home_id DO UPDATE
SET end_ts = excluded.end_ts, facts = excluded.facts, kwh = excluded.kwh, detected_at = now()
""")


async def _store(session, home_id, motif, device, start, end, facts, kwh) -> None:
    await session.execute(UPSERT, {"h": home_id, "motif": motif, "device": device,
                                   "start": start, "end": end,
                                   "facts": json.dumps(facts, default=str), "kwh": kwh})


def _round(x: float, places: int = 2) -> float:
    return round(float(x), places)


async def _night_baseline(session, home_id, tz, lo, hi) -> int:
    rows = (await session.execute(text("""
        WITH nights AS (
            SELECT (r.bucket AT TIME ZONE :tz)::date AS night, min(r.avg_w) AS min_w
            FROM energy.reading_1h r JOIN energy.series s ON s.series_id = r.series_id
            WHERE s.home_id = :h AND s.kind = 'main' AND r.bucket >= :lo AND r.bucket < :hi
              AND extract(hour FROM r.bucket AT TIME ZONE :tz) < :hours
            GROUP BY 1
        ),
        med AS (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY min_w) AS m, count(*) AS n
                FROM nights)
        SELECT night, min_w, m FROM nights, med WHERE n >= 3 AND m > 0
    """), {"h": home_id, "tz": tz, "lo": lo, "hi": hi, "hours": NIGHT_HOURS})).all()
    for r in rows:
        start = local_midnight(r.night, tz)
        excess = max(r.min_w - r.m, 0)
        await _store(session, home_id, "night_baseline", None, start,
                     start + dt.timedelta(hours=NIGHT_HOURS),
                     {"night": r.night.isoformat(), "min_w": _round(r.min_w, 0),
                      "median_w": _round(r.m, 0), "excess_w": _round(excess, 0),
                      "ratio": _round(r.min_w / r.m)},
                     _round(excess * NIGHT_HOURS / 1000, 3))
    return len(rows)


async def _daily(session, home_id, tz, lo, hi) -> list:
    return (await session.execute(text("""
        SELECT (r.bucket AT TIME ZONE :tz)::date AS day, r.energy_wh / 1000 AS kwh
        FROM energy.reading_1d r JOIN energy.series s ON s.series_id = r.series_id
        WHERE s.home_id = :h AND s.kind = 'main' AND r.bucket >= :lo AND r.bucket < :hi
        ORDER BY 1
    """), {"h": home_id, "tz": tz, "lo": lo, "hi": hi})).all()


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


async def _day_above_usual(session, home_id, tz, days) -> int:
    if len(days) < 3:
        return 0
    median = _median([d.kwh for d in days])
    if median <= 0:
        return 0
    for d in days:
        start = local_midnight(d.day, tz)
        excess = max(d.kwh - median, 0)
        await _store(session, home_id, "day_above_usual", None, start,
                     start + dt.timedelta(days=1),
                     {"day": d.day.isoformat(), "kwh": _round(d.kwh),
                      "median_kwh": _round(median), "excess_kwh": _round(excess),
                      "ratio": _round(d.kwh / median)},
                     _round(excess, 3))
    return len(days)


async def _repeat_use(session, home_id, lo, hi) -> int:
    n = 0
    for code, (k, minutes) in REPEAT.items():
        rows = (await session.execute(text("""
            WITH c AS (
                SELECT c.device_id, c.start_ts, c.end_ts,
                       count(*) OVER w AS n, sum(c.energy_wh) OVER w AS wh,
                       max(c.end_ts) OVER w AS last_end,
                       lag(c.start_ts) OVER (PARTITION BY c.device_id ORDER BY c.start_ts) AS prev
                FROM insight.device_cycle c
                JOIN core.device d ON d.id = c.device_id AND d.home_id = c.home_id
                WHERE c.home_id = :h AND d.device_type_code = :code
                  AND c.start_ts >= :lo AND c.start_ts < :hi
                WINDOW w AS (PARTITION BY c.device_id ORDER BY c.start_ts
                             RANGE BETWEEN CURRENT ROW AND make_interval(mins => :m) FOLLOWING)
            )
            SELECT device_id, start_ts, last_end, n, wh FROM c
            WHERE n >= :k AND (prev IS NULL OR start_ts - prev > make_interval(mins => :m))
        """), {"h": home_id, "code": code, "lo": lo, "hi": hi, "k": k, "m": minutes})).all()
        for r in rows:
            await _store(session, home_id, "repeat_use", r.device_id, r.start_ts, r.last_end,
                         {"cycles": r.n, "window_min": minutes, "kwh": _round(r.wh / 1000, 3)},
                         _round(r.wh / 1000, 3))
            n += 1
    return n


async def _long_run(session, home_id, lo, hi) -> int:
    rows = (await session.execute(text("""
        SELECT c.device_id, c.start_ts, c.end_ts, c.energy_wh, d.device_type_code AS code,
               extract(epoch FROM c.end_ts - c.start_ts) / 60 AS minutes
        FROM insight.device_cycle c
        JOIN core.device d ON d.id = c.device_id AND d.home_id = c.home_id
        WHERE c.home_id = :h AND c.start_ts >= :lo AND c.start_ts < :hi
          AND d.device_type_code = ANY(:codes)
    """), {"h": home_id, "lo": lo, "hi": hi, "codes": list(LONG_RUN_MIN)})).all()
    n = 0
    for r in rows:
        limit = LONG_RUN_MIN[r.code]
        if r.minutes > limit:
            await _store(session, home_id, "long_run", r.device_id, r.start_ts, r.end_ts,
                         {"minutes": _round(r.minutes, 0), "limit_min": limit,
                          "kwh": _round(r.energy_wh / 1000, 3)}, _round(r.energy_wh / 1000, 3))
            n += 1
    return n


def cycle_start(day: dt.date, cycle_day: int) -> dt.date:
    """First day of the billing cycle that contains `day`."""
    if day.day >= cycle_day:
        return day.replace(day=cycle_day)
    prev = day.replace(day=1) - dt.timedelta(days=1)
    return prev.replace(day=min(cycle_day, prev.day))


def tier_of(tiers: list[dict[str, Any]], kwh: float) -> dict[str, Any]:
    """The tier a monthly kWh total ends in (tiers: from_kwh, to_kwh or None, price)."""
    for t in tiers:
        if t["to_kwh"] is None or kwh <= t["to_kwh"]:
            return t
    return tiers[-1]


async def _tier_crossing(session, home_id, tz, today, days, home, tariff) -> tuple[int, float]:
    """Month-to-date + average daily kWh x days left, against the tiers. Returns (n, projection)."""
    if not days or not tariff.get("tiers"):
        return 0, 0.0
    cycle_day = home.get("billing_cycle_day") or 1
    start = cycle_start(today, cycle_day)
    nxt = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=cycle_day)
    month = (await session.execute(text("""
        SELECT coalesce(sum(r.energy_wh), 0) / 1000 AS kwh
        FROM energy.reading_1d r JOIN energy.series s ON s.series_id = r.series_id
        WHERE s.home_id = :h AND s.kind = 'main' AND r.bucket >= :a AND r.bucket < :b
    """), {"h": home_id, "a": local_midnight(start, tz), "b": local_midnight(today, tz)})).scalar()
    avg = sum(d.kwh for d in days) / len(days)
    days_left = (nxt - today).days
    projected = float(month) + avg * days_left
    tiers = tariff["tiers"]
    now_tier, end_tier = tier_of(tiers, float(month)), tier_of(tiers, projected)
    if end_tier["tier_no"] <= now_tier["tier_no"]:
        return 0, projected
    cut = (projected - end_tier["from_kwh"]) / days_left if days_left else 0.0
    await _store(session, home_id, "tier_crossing", None, local_midnight(start, tz),
                 local_midnight(nxt, tz),
                 {"month_kwh": _round(month), "avg_daily_kwh": _round(avg), "days_left": days_left,
                  "projected_kwh": _round(projected, 0), "tier": end_tier["tier_no"],
                  "tier_from_kwh": end_tier["from_kwh"], "cut_kwh_per_day": _round(cut, 1)},
                 _round(projected - end_tier["from_kwh"], 3))
    return 1, projected


async def detect(session: AsyncSession, home_id: uuid.UUID, today: dt.date,
                 home: dict[str, Any], tariff: dict[str, Any]) -> dict[str, Any]:
    """Run the five detectors over the last 7 days; returns counts and the monthly projection."""
    tz = home["timezone"]
    lo, hi = window(today, tz)
    days = await _daily(session, home_id, tz, lo, hi)
    counts = {
        "night_baseline": await _night_baseline(session, home_id, tz, lo, hi),
        "day_above_usual": await _day_above_usual(session, home_id, tz, days),
        "repeat_use": await _repeat_use(session, home_id, lo, hi),
        "long_run": await _long_run(session, home_id, lo, hi),
    }
    counts["tier_crossing"], projected = await _tier_crossing(
        session, home_id, tz, today, days, home, tariff)
    await session.commit()
    avg = sum(d.kwh for d in days) / len(days) if days else 0.0
    return {"counts": counts, "monthly_kwh": projected or avg * 30}
