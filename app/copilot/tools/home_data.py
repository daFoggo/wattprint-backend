"""Reads and writes on the home's data. Copilot-login tools take the raw asyncpg connection
of db_connector.copilot_tx; app-login tools take the app session and always filter by the
run's home."""

import datetime as dt
import uuid
from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...services.billing import compute_bill
from ..skills.advice import ACCEPT, REJECT, SNOOZE
from ..skills.motifs import cycle_start
from ..utils.helpers import as_json
from . import sql_builder as sql


async def home_facts(conn, tz: str) -> dict[str, Any]:
    """The latest local day with main-meter data and the appliances NILM tracks."""
    latest = await conn.fetchval(
        "SELECT max((bucket AT TIME ZONE $1)::date) FROM copilot_ro.reading_1d WHERE kind = 'main'",
        tz,
    )
    tracked = await conn.fetch(
        "SELECT d.id::text AS id, d.name FROM copilot_ro.device d "
        "WHERE d.deleted_at IS NULL AND EXISTS (SELECT 1 FROM copilot_ro.series s "
        "WHERE s.device_id = d.id AND s.kind = 'device') ORDER BY d.name"
    )
    return {"latest_date": latest.isoformat() if latest else None,
            "tracked": [dict(r) for r in tracked]}


async def plug_coverage(conn, device_ids: list[uuid.UUID], lo: dt.datetime, hi: dt.datetime
                        ) -> dict[str, int]:
    """Minutes the plug series of each device cover in [lo, hi)."""
    rows = await conn.fetch(
        "SELECT device_id::text AS id, coalesce(sum(covered_minutes), 0)::int AS m "
        "FROM copilot_ro.reading_1d WHERE kind = 'plug' AND device_id = ANY($1::uuid[]) "
        "AND bucket >= $2 AND bucket < $3 GROUP BY device_id",
        device_ids, lo, hi,
    )
    got = {r["id"]: r["m"] for r in rows}
    return {str(d): got.get(str(d), 0) for d in device_ids}


async def device_names(conn) -> dict[str, str]:
    return {r["id"]: r["name"] for r in await conn.fetch(
        "SELECT id::text AS id, name FROM copilot_ro.device")}


async def read_suggestions(conn) -> list[dict[str, Any]]:
    """Open suggestions with their evidence, best saving first."""
    rows = await conn.fetch(
        "SELECT s.id::text AS id, s.kind, s.title, s.body, s.expected_kwh::float AS expected_kwh, "
        "s.expected_amount::float AS expected_amount, s.evidence, d.name AS device "
        "FROM copilot_ro.suggestion s LEFT JOIN copilot_ro.device d ON d.id = s.device_id "
        "WHERE s.status IN ('proposed', 'shown') "
        "ORDER BY s.expected_amount DESC NULLS LAST, s.created_at DESC LIMIT 3"
    )
    return [{**dict(r), "evidence": as_json(r["evidence"])} for r in rows]


async def billing(session: AsyncSession, home: dict[str, Any], day: dt.date, today: dt.date
                  ) -> dict[str, Any]:
    """The existing tiered bill of the billing cycle that contains `day` (upserted)."""
    start = cycle_start(day, home.get("billing_cycle_day") or 1)
    now = sql.local_midnight(today + dt.timedelta(days=1), home["timezone"])
    now = min(now, dt.datetime.now(UTC))
    bill = await compute_bill(session, uuid.UUID(home["id"]), start, now=now)
    await session.commit()
    return {
        "period_start": bill.period_start.isoformat(), "period_end": bill.period_end.isoformat(),
        "kwh": float(bill.kwh_total), "amount_before_vat": float(bill.amount_before_vat),
        "vat": float(bill.vat_amount), "amount": float(bill.amount_total),
        "coverage": float(bill.coverage), "status": bill.status,
    }


async def feedback_stats(session: AsyncSession, home_id: uuid.UUID, today: dt.date
                         ) -> dict[str, dict[str, int]]:
    rows = await session.execute(text("""
        SELECT s.kind,
               count(*) FILTER (WHERE f.action = :acc) AS accepts,
               count(*) FILTER (WHERE f.action = :rej) AS rejects,
               count(*) FILTER (WHERE f.action = :rej AND f.at >= :d30) AS rejected_30d,
               count(*) FILTER (WHERE f.action = :snz AND f.at >= :d7) AS snoozed_7d
        FROM copilot.suggestion s JOIN copilot.suggestion_feedback f ON f.suggestion_id = s.id
        WHERE s.home_id = :h GROUP BY s.kind
    """), {"h": home_id, "acc": ACCEPT, "rej": REJECT, "snz": SNOOZE,
           "d30": dt.datetime.combine(today - dt.timedelta(days=30), dt.time(), UTC),
           "d7": dt.datetime.combine(today - dt.timedelta(days=7), dt.time(), UTC)})
    stats = {r.kind: dict(r._mapping) for r in rows}
    for kind, n in await session.execute(text(
        "SELECT kind, count(*) FROM copilot.suggestion WHERE home_id = :h "
        "AND status IN ('proposed', 'shown') GROUP BY kind"), {"h": home_id}):
        stats.setdefault(kind, {})["open"] = n
    return stats


async def measure_savings(session: AsyncSession, home_id: uuid.UUID, today: dt.date, tz: str
                          ) -> list[str]:
    """Suggestions accepted 7+ days ago without a measure: kWh 7 days before vs 7 days after.

    The measure is the home's (or the device's) kWh, not the motif's own figure; the method text
    says so.
    """
    rows = (await session.execute(text("""
        SELECT s.id, s.device_id, min(f.at) AS accepted_at
        FROM copilot.suggestion s JOIN copilot.suggestion_feedback f ON f.suggestion_id = s.id
        WHERE s.home_id = :h AND f.action = :acc
          AND NOT EXISTS (SELECT 1 FROM copilot.savings_measure m WHERE m.suggestion_id = s.id)
        GROUP BY s.id, s.device_id
    """), {"h": home_id, "acc": ACCEPT})).all()
    measured = []
    for r in rows:
        day = r.accepted_at.astimezone(ZoneInfo(tz)).date()
        if day + dt.timedelta(days=7) > today:
            continue
        kind, view = ("device", "device_estimate_1d") if r.device_id else ("main", "reading_1d")

        async def kwh(a: dt.date, b: dt.date, kind=kind, view=view, device=r.device_id) -> float:
            return float(await session.scalar(text(f"""
                SELECT coalesce(sum(x.energy_wh), 0) / 1000 FROM energy.{view} x
                JOIN energy.series s ON s.series_id = x.series_id
                WHERE s.home_id = :h AND s.kind = :k
                  AND (CAST(:d AS uuid) IS NULL OR s.device_id = :d)
                  AND x.bucket >= :a AND x.bucket < :b
            """), {"h": home_id, "k": kind, "d": device, "a": sql.local_midnight(a, tz),
                   "b": sql.local_midnight(b, tz)}))

        before = await kwh(day - dt.timedelta(days=7), day)
        after = await kwh(day, day + dt.timedelta(days=7))
        await session.execute(text(
            "INSERT INTO copilot.savings_measure (suggestion_id, baseline_kwh, actual_kwh, "
            "method, measured_at) VALUES (:s, :b, :a, :m, now())"),
            {"s": r.id, "b": round(before, 3), "a": round(after, 3),
             "m": "kWh of the 7 local days after acceptance vs the 7 days before; "
                  "not weather adjusted"})
        measured.append(str(r.id))
    await session.commit()
    return measured
