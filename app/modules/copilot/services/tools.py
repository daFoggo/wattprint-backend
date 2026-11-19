import inspect
import json
import logging
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.billing.api import bill_history, current_bill, forecast_bill
from app.modules.energy.api import device_breakdown, weather_at
from app.modules.home.api import Device, Home, Province
from app.modules.insight.api import cohort_for, list_alerts

from ..models import ScopeToken, Suggestion

log = logging.getLogger("copilot.tools")
ICT = timezone(timedelta(hours=7))
TIERS = ("measured", "estimated", "inferred")  # most to least certain
MAX_ROWS_TO_LLM = 30


@dataclass
class Ctx:
    session: AsyncSession
    home_id: uuid.UUID
    now: datetime
    lang: str


@dataclass
class Outcome:
    """A tool's result: `data` goes to the model; the rest builds the reply, never the model."""

    data: Any
    detail: str  # the trace's line under the step
    tier: str = "measured"
    sources: list[str] = field(default_factory=list)
    widgets: list[dict[str, Any]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    sql: str | None = None


def _today(ctx: Ctx) -> date:
    return ctx.now.astimezone(ICT).date()


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=ICT).astimezone(UTC)


def _f(x: Decimal | float | None, digits: int = 2) -> float | None:
    return None if x is None else round(float(x), digits)


def _vi(ctx: Ctx, vi: str, en: str) -> str:
    return vi if ctx.lang == "vi" else en


async def _avg_price(ctx: Ctx) -> float | None:
    """VND per kWh of the running cycle, VAT included; None without a tariff or any kWh yet."""
    try:
        bill = await current_bill(ctx.session, ctx.home_id, ctx.now)
    except LookupError:
        return None
    return float(bill.amount_total / bill.kwh) if bill.kwh else None


async def _daily_kwh(ctx: Ctx, lo: date, hi: date) -> dict[date, float]:
    """Main-meter kWh per local day in [lo, hi)."""
    rows = await ctx.session.execute(
        text(
            "SELECT r.bucket, sum(r.energy_wh) / 1000 AS kwh FROM public.reading_1d r "
            "JOIN public.tb_series s USING (series_id) WHERE s.home_id = :h AND s.kind = 'main' "
            "AND s.metric = 'power_w' AND r.bucket >= :lo AND r.bucket < :hi GROUP BY r.bucket"
        ),
        {"h": ctx.home_id, "lo": _midnight(lo), "hi": _midnight(hi)},
    )
    return {r.bucket.astimezone(ICT).date(): float(r.kwh) for r in rows}


async def devices_breakdown(ctx: Ctx, days: int = 30) -> Outcome:
    days = max(1, min(int(days), 90))
    since = _midnight(_today(ctx) - timedelta(days=days - 1))
    parts = await device_breakdown(ctx.session, ctx.home_id, since, ctx.now)
    names = dict(
        (
            await ctx.session.execute(
                select(Device.id, Device.name).where(Device.home_id == ctx.home_id)
            )
        ).all()
    )
    rows = [
        {"id": str(p.device_id), "name": names.get(p.device_id, "?"), "kwh": _f(p.kwh, 1)}
        for p in parts
    ]
    return Outcome(
        data={
            "days": days,
            "devices": rows,
            "note": "estimates of the device recognition model; 'Other' = not recognised",
        },
        detail=_vi(
            ctx,
            f"Mô hình nhận diện thiết bị · {days} ngày",
            f"Device recognition model · {days} days",
        ),
        tier="estimated",
        sources=["nilm"],
        widgets=[
            {
                "kind": "devices",
                "slices": [{"id": r["id"], "label": r["name"], "value": r["kwh"]} for r in rows],
            }
        ],
        links=["devices"],
    )


async def bill_now(ctx: Ctx) -> Outcome:
    try:
        b = await current_bill(ctx.session, ctx.home_id, ctx.now)
    except LookupError:
        return Outcome({"error": "the home has no tariff plan"}, "tb_bill")
    return Outcome(
        data={
            "period": [str(b.period_start), str(b.period_end)],
            "kwh": _f(b.kwh, 1),
            "amount_vnd_with_vat": _f(b.amount_total, 0),
            "vat_rate": _f(b.vat_rate, 3),
            "current_tier": b.tier_no,
            "tiers": [
                {
                    "tier": t.tier_no,
                    "from_kwh": _f(t.from_kwh, 0),
                    "to_kwh": _f(t.to_kwh, 0),
                    "price_per_kwh": _f(t.price_per_kwh, 0),
                    "kwh_used": _f(t.kwh, 1),
                }
                for t in b.tiers
            ],
            "today": {"kwh": _f(b.today_kwh, 2), "vnd": _f(b.today_amount, 0)},
            "data_coverage": _f(b.coverage, 2),
        },
        detail=_vi(ctx, "Công tơ tổng · biểu giá bậc thang", "Main meter · tiered tariff"),
        sources=["tariff", "meter"],
        links=["bill"],
    )


async def bill_forecast(ctx: Ctx) -> Outcome:
    try:
        b = await current_bill(ctx.session, ctx.home_id, ctx.now)
        f = await forecast_bill(ctx.session, ctx.home_id, ctx.now)
    except LookupError:
        return Outcome({"error": "the home has no tariff plan"}, "forecast")
    if f is None:
        return Outcome({"error": "fewer than 7 full days of readings: no forecast yet"}, "forecast")
    current = next(t for t in b.tiers if t.tier_no == b.tier_no)
    limit = f.next.from_kwh if f.next else current.to_kwh
    return Outcome(
        data={
            "period_end": str(f.period_end),
            "kwh_so_far": _f(b.kwh, 1),
            "kwh_at_end": _f(f.kwh, 1),
            "amount_vnd_with_vat_at_end": _f(f.amount, 0),
            "tier_at_end": f.tier_no,
            "next_tier": (
                {"tier": f.next.tier_no, "from_kwh": _f(f.next.from_kwh, 0), "on": str(f.next.on)}
                if f.next
                else None
            ),
            "method": f"same weekday average of the last {f.basis_days} full days",
        },
        detail=_vi(ctx, "Trung bình theo thứ · biểu giá", "Weekday average · tariff"),
        tier="estimated",
        sources=["tariff", "meter"],
        widgets=[
            {
                "kind": "forecast",
                "used": _f(b.kwh, 1),
                "limit": _f(limit, 0),
                "kwh": _f(f.kwh, 1),
                "vnd": _f(f.amount, 0),
            }
        ],
        links=["bill"],
    )


async def bills_past(ctx: Ctx) -> Outcome:
    bills = (await bill_history(ctx.session, ctx.home_id, ctx.now))[-12:]
    return Outcome(
        data=[
            {
                "period": [str(b.period_start), str(b.period_end)],
                "kwh": _f(b.kwh_total, 1),
                "amount_vnd_with_vat": _f(b.amount_total, 0),
                "data_coverage": _f(b.coverage, 2),
            }
            for b in bills
        ]
        or {"error": "no ended billing cycle yet"},
        detail=_vi(ctx, "Hóa đơn các kỳ trước", "Past bills"),
        sources=["tariff", "meter"],
        links=["bill"],
    )


async def compare_periods(ctx: Ctx, period: str = "week") -> Outcome:
    today = _today(ctx)
    if period == "cycle":
        day = await ctx.session.scalar(select(Home.billing_cycle_day).where(Home.id == ctx.home_id))
        start = (
            today.replace(day=day)
            if today.day >= day
            else ((today.replace(day=1) - timedelta(days=1)).replace(day=day))
        )
        prev = (start.replace(day=1) - timedelta(days=1)).replace(day=day)
        n = (today - start).days  # whole days so far
    else:
        period, n = "week", 7
        start, prev = today - timedelta(days=7), today - timedelta(days=14)
    cur = await _daily_kwh(ctx, start, start + timedelta(days=n))
    old = await _daily_kwh(ctx, prev, prev + timedelta(days=n))
    data = [
        {
            "key": str(start + timedelta(days=i)),
            "current": _f(cur.get(start + timedelta(days=i), 0.0), 1),
            "previous": _f(old.get(prev + timedelta(days=i), 0.0), 1),
        }
        for i in range(n)
    ]
    total = (sum(d["current"] for d in data), sum(d["previous"] for d in data))
    return Outcome(
        data={
            "period": period,
            "days": n,
            "current_from": str(start),
            "previous_from": str(prev),
            "kwh_current": round(total[0], 1),
            "kwh_previous": round(total[1], 1),
            "by_day": data,
        },
        detail=_vi(ctx, f"Công tơ tổng · {n} ngày", f"Main meter · {n} days"),
        sources=["meter"],
        widgets=[{"kind": "compare", "period": period, "data": data}] if n else [],
        links=["statistics"],
    )


async def weather(ctx: Ctx) -> Outcome:
    home = await ctx.session.get(Home, ctx.home_id)
    province = await ctx.session.get(Province, home.province_code) if home.province_code else None
    if province is None:
        return Outcome({"error": "the home has no province set (Settings)"}, "OpenWeather")
    try:
        w = await weather_at(province.lat, province.lon, ctx.lang)
    except Exception:  # WeatherUnavailableError, or no key
        return Outcome({"error": "weather is unavailable right now"}, "OpenWeather")
    return Outcome(
        data={
            "place": province.name,
            "now": {
                "temp_c": w.now.temp,
                "feels_like_c": w.now.feels_like,
                "humidity_pct": w.now.humidity,
                "sky": w.now.sky.description,
            },
            "next_24h": [
                {
                    "at": datetime.fromtimestamp(s.dt, ICT).strftime("%H:%M"),
                    "temp_c": s.temp,
                    "rain_chance": s.pop,
                }
                for s in w.next
            ],
        },
        detail=f"OpenWeather · {province.name}",
        tier="inferred",
        sources=["weather"],
        widgets=[
            {
                "kind": "weather",
                "temp": round(w.now.temp),
                "feels": round(w.now.feels_like),
                "humidity": w.now.humidity,
            }
        ],
    )


async def cohort(ctx: Ctx) -> Outcome:
    c = await cohort_for(ctx.session, ctx.home_id)
    if c is None or c.kwh is None:
        why = "fewer than 10 comparable homes" if c is None else "this home lacks data"
        return Outcome({"error": f"no comparison: {why}"}, "cohort_stat")
    median = (float(c.p33) + float(c.p66)) / 2
    return Outcome(
        data={
            "days": c.days,
            "homes": c.homes,
            "compared_with": c.cohort_key,
            "this_home_kwh": _f(c.kwh, 1),
            "percentiles_kwh": {"p10": _f(c.p10, 1), "p90": _f(c.p90, 1)},
            "median_kwh": round(median, 1),
        },
        detail=_vi(ctx, f"Nhà tương tự · {c.homes} hộ", f"Similar homes · {c.homes} homes"),
        sources=["cohort"],
        widgets=[
            {
                "kind": "peers",
                "you": _f(c.kwh, 1),
                "median": round(median, 1),
                "days": c.days,
                "homes": c.homes,
            }
        ],
        links=["statistics"],
    )


async def alerts(ctx: Ctx) -> Outcome:
    rows = [
        (a, d)
        for a, d in await list_alerts(ctx.session, ctx.home_id, None, 10)
        if a.status != "resolved"
    ]
    return Outcome(
        data=[
            {
                "kind": a.kind,
                "severity": a.severity,
                "since": a.ts.astimezone(ICT).isoformat(timespec="minutes"),
                "device": d.name if d else None,
                "figures": a.payload,
            }
            for a, d in rows
        ]
        or {"note": "no open alerts"},
        detail=_vi(ctx, "Cảnh báo của hệ thống", "System alerts"),
        tier="estimated",
        sources=["nilm"],
        links=["devices"],
    )


async def standby(ctx: Ctx, nights: int = 14) -> Outcome:
    nights = max(3, min(int(nights), 30))
    last = (ctx.now.astimezone(ICT) - timedelta(hours=5)).date()  # the last night fully over
    rows = await ctx.session.execute(
        text(
            "WITH m AS (SELECT r.bucket, sum(r.avg_w) AS w FROM public.reading_1m r "
            "JOIN public.tb_series s USING (series_id) WHERE s.home_id = :h AND s.kind = 'main' "
            "AND s.metric = 'power_w' AND r.bucket >= :lo AND r.bucket < :hi "
            "AND extract(hour FROM r.bucket AT TIME ZONE 'Asia/Ho_Chi_Minh') < 5 "
            "GROUP BY r.bucket) "
            "SELECT (bucket AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AS night, "
            "percentile_cont(0.05) WITHIN GROUP (ORDER BY w) AS p5, count(*) AS n "
            "FROM m GROUP BY night ORDER BY night"
        ),
        {
            "h": ctx.home_id,
            "lo": _midnight(last - timedelta(days=nights - 1)),
            "hi": _midnight(last + timedelta(days=1)),
        },
    )
    watts = [(r.night, float(r.p5)) for r in rows if r.n >= 0.8 * 300]
    if not watts:
        return Outcome({"error": "no full night of readings yet"}, "reading_1m")
    base = statistics.median(w for _, w in watts)
    kwh_month = base * 24 * 30 / 1000
    price = await _avg_price(ctx)
    vnd = kwh_month * price if price else None
    return Outcome(
        data={
            "method": "5th percentile of whole-home power, 00:00-05:00, per night",
            "nights": [{"night": str(d), "watts": round(w)} for d, w in watts],
            "typical_watts": round(base),
            "kwh_per_month": round(kwh_month, 1),
            "vnd_per_month": round(vnd) if vnd else None,
        },
        detail=_vi(ctx, f"Công tơ tổng · {len(watts)} đêm", f"Main meter · {len(watts)} nights"),
        tier="estimated",
        sources=["meter", "tariff"],
        widgets=[
            {
                "kind": "standby",
                "watts": [round(w) for _, w in watts],
                "kwh": round(kwh_month, 1),
                "vnd": round(vnd) if vnd else None,
            }
        ],
        links=["statistics"],
    )


async def query_data(ctx: Ctx, question: str) -> Outcome:
    """Free-form data question through text2sql, limited to this home by a 5-minute scope token."""
    if not settings.text2sql_connection_id:
        return Outcome({"error": "free-form data questions are not configured"}, "text2sql")
    token = ScopeToken(home_id=ctx.home_id)
    ctx.session.add(token)
    await ctx.session.commit()  # text2sql reads it from its own connection
    headers = (
        {"X-Service-Key": settings.text2sql_service_key} if settings.text2sql_service_key else {}
    )
    body = {
        "connection_id": settings.text2sql_connection_id,
        "question": question[:2000],
        "scope_token": str(token.token),
        "time_zone": "Asia/Ho_Chi_Minh",  # tb_home.timezone is CHECKed to it
    }
    sql, columns, rows, answer, status = None, [], [], "", "error"
    try:
        async with (
            httpx.AsyncClient(base_url=settings.text2sql_url, timeout=60) as client,
            client.stream("POST", "/api/v1/text2sql/chat", json=body, headers=headers) as res,
        ):
            if res.status_code != 200:
                await res.aread()
                return Outcome({"error": f"text2sql answered {res.status_code}"}, "text2sql")
            event = None
            async for line in res.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    d = json.loads(line[6:])
                    if event == "data":
                        sql, columns, rows = d.get("sql"), d.get("columns", []), d.get("rows", [])
                    elif event == "token":
                        answer += d.get("text", "")
                    elif event == "done":
                        status = d.get("status", "error")
    except httpx.HTTPError:
        return Outcome({"error": "text2sql is unreachable"}, "text2sql")
    return Outcome(
        data={
            "status": status,
            "columns": [
                c.get("label") or c.get("name") if isinstance(c, dict) else c for c in columns
            ],
            "rows": rows[:MAX_ROWS_TO_LLM],
            "row_count": len(rows),
            "summary": answer,
        },
        detail=_vi(ctx, "Truy vấn chỉ đọc dữ liệu nhà bạn", "Read-only query of your home's data"),
        tier="estimated",
        sources=["meter"],
        sql=sql,
    )


async def propose_plan(ctx: Ctx, title: str, tasks: list[dict[str, Any]]) -> Outcome:
    tasks = [
        {
            "label": str(t.get("label", ""))[:120],
            "detail": str(t.get("detail", ""))[:300],
            "kwh_month": max(0.0, float(t.get("kwh_month") or 0)),
        }
        for t in tasks[:6]
        if t.get("label")
    ]
    if not tasks:
        return Outcome({"error": "a plan needs at least one task"}, "tb_suggestion")
    kwh = round(sum(t["kwh_month"] for t in tasks), 1)
    price = await _avg_price(ctx)
    vnd = round(kwh * price) if price else None
    plan = Suggestion(
        home_id=ctx.home_id,
        kind="plan",
        title=title[:200] or "Plan",
        body=json.dumps(tasks, ensure_ascii=False),
        expected_kwh=Decimal(str(kwh)),
        expected_amount=Decimal(vnd) if vnd is not None else None,
    )
    ctx.session.add(plan)
    await ctx.session.commit()  # the reply names it: a later failing tool must not roll it back
    return Outcome(
        data={"plan_id": str(plan.id), "kwh_per_month": kwh, "vnd_per_month": vnd},
        detail=_vi(ctx, "Kế hoạch tiết kiệm", "Savings plan"),
        tier="estimated",
        sources=["tariff"],
        widgets=[
            {
                "kind": "plan",
                "id": str(plan.id),
                "tasks": [{"label": t["label"], "detail": t["detail"]} for t in tasks],
                "kwh": kwh,
                "vnd": vnd,
                "status": "proposed",
            }
        ],
    )


def _fn(name: str, description: str, properties: dict | None = None, required=()) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


Tool = Callable[..., Awaitable[Outcome]]
TOOLS: dict[str, tuple[Tool, dict]] = {
    "devices_breakdown": (
        devices_breakdown,
        _fn(
            "devices_breakdown",
            "kWh per device over the last N days (NILM estimates from the main meter).",
            {"days": {"type": "integer", "minimum": 1, "maximum": 90}},
        ),
    ),
    "current_bill": (
        bill_now,
        _fn("current_bill", "The running billing cycle so far: kWh, VND, tiers, today."),
    ),
    "bill_forecast": (
        bill_forecast,
        _fn("bill_forecast", "The bill at the end of this cycle and when the next tier starts."),
    ),
    "bill_history": (bills_past, _fn("bill_history", "Ended cycles' bills.")),
    "compare_periods": (
        compare_periods,
        _fn(
            "compare_periods",
            "Daily kWh of this week (last 7 days) or this billing cycle against the previous one.",
            {"period": {"type": "string", "enum": ["week", "cycle"]}},
            ["period"],
        ),
    ),
    "weather": (weather, _fn("weather", "Weather now and the next 24 h at the home's province.")),
    "cohort": (cohort, _fn("cohort", "This home's last 30 days against similar homes.")),
    "alerts": (alerts, _fn("alerts", "Open alerts: devices running long, standby, tiers.")),
    "standby": (
        standby,
        _fn(
            "standby",
            "Always-on power: the lowest night-time load per night, its kWh and VND per month.",
            {"nights": {"type": "integer", "minimum": 3, "maximum": 30}},
        ),
    ),
    "query_data": (
        query_data,
        _fn(
            "query_data",
            "Any other question about this home's own data that the other tools do not answer: "
            "a specific day or hour, a device's runs (how many, how long, when), peaks, trends. "
            "Answered by a read-only SQL query; ask one precise question.",
            {"question": {"type": "string", "maxLength": 500}},
            ["question"],
        ),
    ),
    "propose_plan": (
        propose_plan,
        _fn(
            "propose_plan",
            "Save a savings plan the user can start: 2-5 concrete tasks from this home's data, "
            "each with the kWh per month it saves (estimate it from the tools' figures).",
            {
                "title": {"type": "string", "maxLength": 200},
                "tasks": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "detail": {"type": "string"},
                            "kwh_month": {"type": "number", "minimum": 0},
                        },
                        "required": ["label", "detail", "kwh_month"],
                        "additionalProperties": False,
                    },
                },
            },
            ["title", "tasks"],
        ),
    ),
}
SPECS = [spec for _, spec in TOOLS.values()]


async def run_tool(ctx: Ctx, name: str, args: dict[str, Any]) -> tuple[Outcome, bool, int]:
    """(outcome, ok, ms). A bad call or a failing tool gives the model an error, not the user a
    500; the failure is logged."""
    started = time.monotonic()
    fn = TOOLS.get(name, (None,))[0]
    try:
        if fn is None:
            raise TypeError(f"no tool {name}")
        inspect.signature(fn).bind(ctx, **args)
    except TypeError as e:  # the model named a tool or arguments that do not exist
        return Outcome({"error": f"invalid call: {e}"}, name), False, 0
    try:
        outcome = await fn(ctx, **args)
    except Exception:
        log.exception("copilot tool %s failed", name)
        await ctx.session.rollback()
        outcome = Outcome({"error": "this tool failed; answer without it"}, name)
    ok = not (isinstance(outcome.data, dict) and "error" in outcome.data)
    return outcome, ok, int((time.monotonic() - started) * 1000)
