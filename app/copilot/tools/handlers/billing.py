"""Bill, tariff and forecast tools. The money math is the tiered tariff of billing.tariff_*."""

import datetime as dt
import uuid
from datetime import UTC
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from ....models import ForecastSnapshot, TariffTier, TariffVersion
from ...agents.state import Fact
from ...skills import answer_facts
from ...skills.motifs import cycle_start, tier_of
from .. import db_connector as db
from .. import home_data
from .. import sql_builder as sql
from ..registry import RunContext, handler


class DayArgs(BaseModel):
    day: dt.date | None = Field(default=None, description="a local day inside the billing "
                                "cycle; empty = the latest day with data")


class DateArgs(BaseModel):
    date: dt.date | None = Field(default=None, description="the day the tariff must be valid "
                                 "on; empty = the start of the current billing cycle")


class CycleArgs(BaseModel):
    cycle_start: dt.date | None = Field(default=None, description="first day of the billing "
                                        "cycle; empty = the current cycle")


class ForecastArgs(BaseModel):
    until: dt.date | None = Field(default=None, description="last day to forecast; empty = the "
                                  "end of the current billing cycle")
    method: Literal["mean_last_7_days"] = "mean_last_7_days"


class KwhArgs(BaseModel):
    kwh: float | None = Field(default=None, ge=0, description="kWh to price; empty = the "
                              "forecast of this run")


def _latest(rc: RunContext) -> dt.date:
    latest = rc.home.get("latest_date")
    return min(dt.date.fromisoformat(latest), rc.today) if latest else rc.today - dt.timedelta(1)


def _cycle(rc: RunContext, day: dt.date | None = None) -> tuple[dt.date, dt.date]:
    start = cycle_start(day or _latest(rc), rc.home.get("billing_cycle_day") or 1)
    nxt = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=start.day)
    return start, nxt - dt.timedelta(days=1)


async def tariff_on(rc: RunContext, day: dt.date) -> dict:
    """The tariff version of the home's plan valid on `day`: tiers and VAT."""
    async with rc.ctx.app()() as s:
        version = await s.scalar(
            select(TariffVersion)
            .where(TariffVersion.plan_code == rc.home.get("tariff_plan"),
                   TariffVersion.valid_from <= day,
                   (TariffVersion.valid_to.is_(None)) | (TariffVersion.valid_to >= day))
            .order_by(TariffVersion.valid_from.desc()).limit(1))
        if version is None:
            return {"version_id": None, "vat_rate": 0.0, "tiers": []}
        tiers = (await s.execute(select(TariffTier).where(TariffTier.version_id == version.id)
                                 .order_by(TariffTier.tier_no))).scalars()
        return {"version_id": str(version.id), "plan": version.plan_code,
                "valid_from": str(version.valid_from), "vat_rate": float(version.vat_rate),
                "tiers": [{"tier_no": t.tier_no, "from_kwh": float(t.from_kwh),
                           "to_kwh": float(t.to_kwh) if t.to_kwh is not None else None,
                           "price": float(t.price_per_kwh)} for t in tiers]}


def price_tiers(kwh: float, tariff: dict) -> dict:
    """Cumulative tiers (as services.billing): kWh and money per tier, VAT on the total."""
    lines, before = [], 0.0
    for t in tariff["tiers"]:
        top = kwh if t["to_kwh"] is None else min(kwh, t["to_kwh"])
        part = max(top - t["from_kwh"], 0.0)
        if part > 0:
            lines.append({"tier_no": t["tier_no"], "kwh": round(part, 3),
                          "amount": round(part * t["price"])})
            before += part * t["price"]
    vat = before * tariff["vat_rate"]
    return {"kwh": round(kwh, 3), "tiers": lines, "amount_before_vat": round(before),
            "vat": round(vat), "amount": round(before + vat)}


async def _kwh(rc: RunContext, start: dt.date, end: dt.date) -> float:
    tz = rc.home["timezone"]
    async with db.copilot_tx(rc.ctx.copilot(), rc.token) as conn:
        wh = await conn.fetchval(
            "SELECT coalesce(sum(energy_wh), 0) FROM copilot_ro.reading_1d WHERE kind = 'main' "
            "AND bucket >= $1 AND bucket < $2",
            sql.local_midnight(start, tz), sql.local_midnight(end + dt.timedelta(days=1), tz))
    return round(float(wh) / 1000, 3)


@handler("compute_bill", DayArgs)
async def compute_bill(args: DayArgs, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        cost = await home_data.billing(s, rc.home, args.day or _latest(rc), rc.today)
    data = {**cost, "source": "measured by the main meter (not a NILM estimate)",
            "coverage_means": "share of the billing cycle so far that has meter readings; the "
                              "amount prices the kWh measured so far"}
    return {"data": data, "facts": answer_facts.cost_facts(cost, rc.lang), "unit": "VND",
            "api": {"cost": cost}}


@handler("bill_by_tier", DayArgs)
async def bill_by_tier(args: DayArgs, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        cost = await home_data.billing(s, rc.home, args.day or _latest(rc), rc.today)
    tariff = await tariff_on(rc, dt.date.fromisoformat(cost["period_start"]))
    split = price_tiers(cost["kwh"], tariff)
    vi = rc.lang == "vi"
    facts = [Fact(k=f"{'Bậc' if vi else 'Tier'} {t['tier_no']}",
                  v=f"{answer_facts._num(t['kwh'])} kWh · {answer_facts._vnd(t['amount'])} đ")
             for t in split["tiers"]]
    return {"data": {"period_start": cost["period_start"], "period_end": cost["period_end"],
                     **split}, "facts": facts, "unit": "VND"}


@handler("search_price", DateArgs)
async def search_price(args: DateArgs, rc: RunContext) -> dict:
    tariff = await tariff_on(rc, args.date or _cycle(rc)[0])
    if not tariff["tiers"]:
        return {"ok": False, "error": "the home has no tariff valid on that day"}
    return {"data": tariff}


@handler("usage_to_date", CycleArgs)
async def usage_to_date(args: CycleArgs, rc: RunContext) -> dict:
    start, end = _cycle(rc, args.cycle_start)
    latest = _latest(rc)
    kwh = await _kwh(rc, start, latest)
    return {"data": {"cycle_start": str(start), "cycle_end": str(end), "latest_date": str(latest),
                     "days": (latest - start).days + 1, "kwh": kwh}, "unit": "kWh"}


@handler("forecast_usage", ForecastArgs)
async def forecast_usage(args: ForecastArgs, rc: RunContext) -> dict:
    start, end = _cycle(rc)
    until = args.until or end
    latest = _latest(rc)
    to_date = rc.results.get("usage_to_date") or (await usage_to_date(CycleArgs(), rc))["data"]
    last7 = await _kwh(rc, latest - dt.timedelta(days=6), latest)
    per_day = last7 / 7
    days_left = max((until - latest).days, 0)
    kwh = round(to_date["kwh"] + per_day * days_left, 2)
    tariff = await tariff_on(rc, start)
    priced = price_tiers(kwh, tariff) if tariff["tiers"] else {"amount": 0}
    async with rc.ctx.app()() as s:
        s.add(ForecastSnapshot(home_id=uuid.UUID(rc.home["id"]), generated_at=dt.datetime.now(UTC),
                               horizon_date=until, kwh=kwh, amount=priced["amount"],
                               model_version=args.method))
        await s.commit()
    vi = rc.lang == "vi"
    return {"data": {"to_date_kwh": to_date["kwh"], "last_7_days_kwh": last7,
                     "per_day_kwh": round(per_day, 2), "days_left": days_left,
                     "until": str(until), "forecast_kwh": kwh, "method": args.method},
            "facts": [Fact(k=f"Dự báo đến {until:%d/%m}" if vi else f"Forecast to {until:%d/%m}",
                           v=f"{answer_facts._num(kwh)} kWh")],
            "unit": "kWh"}


@handler("price_kwh", KwhArgs)
async def price_kwh(args: KwhArgs, rc: RunContext) -> dict:
    kwh = args.kwh if args.kwh is not None else (rc.results.get("forecast_usage") or {}).get(
        "forecast_kwh")
    if kwh is None:
        return {"ok": False, "error": "no kWh to price"}
    tariff = rc.results.get("search_price") or await tariff_on(rc, _cycle(rc)[0])
    priced = price_tiers(kwh, tariff)
    vi = rc.lang == "vi"
    return {"data": priced, "unit": "VND",
            "facts": [Fact(k="Thành tiền dự kiến (gồm VAT)" if vi
                           else "Expected amount (incl. VAT)",
                           v=f"{answer_facts._vnd(priced['amount'])} đ")]}


@handler("tier_gap")
async def tier_gap(args, rc: RunContext) -> dict:
    forecast = (rc.results.get("forecast_usage")
                or (await forecast_usage(ForecastArgs(), rc))["data"])
    tariff = rc.results.get("search_price") or await tariff_on(rc, _cycle(rc)[0])
    kwh, days = forecast["forecast_kwh"], forecast["days_left"]
    tier = tier_of(tariff["tiers"], kwh)
    over = max(kwh - tier["from_kwh"], 0.0) if tier["tier_no"] > 1 else 0.0
    cut = round(over / days, 2) if days else None
    vi = rc.lang == "vi"
    return {"data": {"forecast_kwh": kwh, "tier_no": tier["tier_no"],
                     "tier_from_kwh": tier["from_kwh"], "over_kwh": round(over, 2),
                     "days_left": days, "cut_per_day_kwh": cut},
            "facts": [Fact(k="Bậc dự kiến" if vi else "Expected tier", v=str(tier["tier_no"])),
                      Fact(k="Cần giảm mỗi ngày" if vi else "Cut per day",
                           v=f"{answer_facts._num(cut)} kWh")]}
