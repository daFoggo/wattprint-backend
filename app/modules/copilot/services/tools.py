import inspect
import json
import logging
import math
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.billing.api import bill_history, current_bill, device_forecasts, forecast_bill
from app.modules.energy.api import device_breakdown, stored_weather, weather_at
from app.modules.expect.api import expected, hourly_actual
from app.modules.home.api import Device, Home, Province
from app.modules.insight.api import (
    WatchError,
    cancel_watch,
    cohort_for,
    create_watch,
    list_alerts,
    list_watches,
)

from ..models import ScopeToken, Suggestion
from ..schemas import (
    ChartSeries,
    ChartWidget,
    CompareWidget,
    DevicesWidget,
    ForecastWidget,
    PeersWidget,
    PlanTask,
    PlanWidget,
    Slice,
    StandbyWidget,
    WatchWidget,
    WeatherWidget,
    Widget,
)

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
    # A long tool's progress, shown as steps while it runs: report(label, detail).
    report: Callable[[str, str], None] = lambda label, detail: None
    user_id: uuid.UUID | None = None  # who asks: a watch is theirs
    question: str = ""
    read_only: bool = False  # a demo viewer: the tools in WRITES answer an error instead


@dataclass
class Outcome:
    """A tool's result: `data` goes to the model; the rest builds the reply, never the model."""

    data: Any
    detail: str  # the trace's line under the step
    tier: str = "measured"
    sources: list[str] = field(default_factory=list)
    widgets: list[Widget] = field(default_factory=list)
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
            DevicesWidget(slices=[Slice(id=r["id"], label=r["name"], value=r["kwh"]) for r in rows])
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


def forecast_data(b, f) -> dict[str, Any]:
    """What Wappi reads of a forecast: the middle, the P10–P90 range, the tier's odds and why it
    moved since yesterday (VND parts)."""
    return {
        "period_end": str(f.period_end),
        "kwh_so_far": _f(b.kwh, 1),
        "kwh_at_end": _f(f.kwh, 1),
        "kwh_range": [_f(f.kwh_p10, 1), _f(f.kwh_p90, 1)],
        "amount_vnd_with_vat_at_end": _f(f.amount, 0),
        "amount_vnd_range": [_f(f.amount_p10, 0), _f(f.amount_p90, 0)],
        "tier_at_end": f.tier_no,
        "next_tier": (
            {
                "tier": f.next.tier_no,
                "from_kwh": _f(f.next.from_kwh, 0),
                "on": str(f.next.on),
                "probability": f.next.probability,
            }
            if f.next
            else None
        ),
        "change": (
            {
                "amount_vnd": _f(f.change.amount, 0),
                "parts_vnd": {k: _f(v, 0) for k, v in f.change.parts.items()},
            }
            if f.change
            else None
        ),
        "accuracy": (
            {
                "source": f.accuracy.source,
                "error_pct": f.accuracy.error_pct,
                "cycles": f.accuracy.cycles,
            }
            if f.accuracy
            else None
        ),
        "simulated": f.simulated or [],
        "method": (
            "contextual model (weather, calendar, routine), range P10-P90"
            if f.method == "context"
            else f"same weekday average of the last {f.basis_days} full days"
        ),
    }


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
    context = f.method == "context"
    return Outcome(
        data=forecast_data(b, f),
        detail=(
            _vi(
                ctx,
                "Mô hình theo thời tiết, lịch · biểu giá",
                "Weather and calendar model · tariff",
            )
            if context
            else _vi(ctx, "Trung bình theo thứ · biểu giá", "Weekday average · tariff")
        ),
        tier="estimated",
        sources=["tariff", "meter", "model"] if context else ["tariff", "meter"],
        widgets=[
            ForecastWidget(
                used=_f(b.kwh, 1), limit=_f(limit, 0), kwh=_f(f.kwh, 1), vnd=_f(f.amount, 0)
            )
        ],
        links=["bill"],
    )


GROUPS = ("weather", "calendar", "occupancy", "trend")


def device_view(d) -> dict[str, Any]:
    """One device's forecast as the model reads it: every figure computed, none to invent."""
    return {
        "device": d.name,
        "simulated": d.simulated,
        "to_cycle_end": {
            "kwh": _f(d.kwh, 1),
            "vnd": _f(d.amount, 0),
            "kwh_range": [_f(d.kwh_p10, 1), _f(d.kwh_p90, 1)],
        },
        "next_days": [
            {"date": x.date.isoformat(), "kwh": _f(x.kwh, 2), "vnd": _f(x.amount, 0)}
            for x in d.next_days
        ],
        "from": "its own model (weather, calendar, routine)"
        if d.method == "model"
        else "its usual for the weekday and hour over the last 4 weeks",
        "certainty": d.confidence,
        "tried_on": {"days": d.backtest_days, "mean_error_pct": d.error_pct},
        "against_usual": None
        if d.explain is None
        else {
            "usual_kwh_day": _f(d.explain.usual_kwh_day, 2),
            "next_7_days_kwh_day": _f(d.explain.forecast_kwh_day, 2),
            "reasons_known": d.explain.explainable,
            "why": [
                {
                    "factor": x.key,
                    "kwh_day": _f(x.kwh_day, 2),
                    "vnd_7_days": _f(x.amount, 0),
                    "ahead": x.now,
                    "last_28_days": x.before,
                    **(
                        {"last_week_c": x.recent_temp, "last_28_days_c": x.usual_temp}
                        if x.recent_temp is not None
                        else {}
                    ),
                }
                for x in d.explain.factors
            ],
        },
        "advice": [
            {
                "what": a.key,
                "saves_vnd": _f(a.saved_amount, 0),
                "saves_kwh": _f(a.saved_kwh, 1),
                "keeps_out_of_tier": a.avoids_tier,
                **a.params,
            }
            for a in d.advice
        ],
    }


async def device_forecast(ctx: Ctx, device: str | None = None) -> Outcome:
    try:
        got = await device_forecasts(ctx.session, ctx.home_id, ctx.now)
    except LookupError:
        return Outcome({"error": "the home has no tariff plan"}, "forecast")
    if got is None:
        return Outcome({"error": "fewer than 7 full days of readings: no forecast yet"}, "forecast")
    rows = got.devices
    if device:
        rows = [d for d in rows if device.casefold() in d.name.casefold()] or rows
    return Outcome(
        data={"cycle_ends": got.period_end.isoformat(), "devices": [device_view(d) for d in rows]},
        detail=_vi(ctx, "Mô hình theo thiết bị · biểu giá", "Per-device model · tariff"),
        tier="estimated",
        sources=["nilm", "model", "tariff"],
        links=["devices"],
    )


def explain_parts(cur: pd.DataFrame, prev: pd.DataFrame) -> dict[str, Any]:
    """Actual against expected for a period, and its change from the previous one split by what
    moved the model's expectation (weather, calendar, routine, trend); the rest is unexplained."""
    actual, previous = float(cur["kwh"].sum()), float(prev["kwh"].sum())
    change = actual - previous
    parts = {g: float(cur[f"c_{g}"].sum() - prev[f"c_{g}"].sum()) for g in GROUPS}
    parts["unexplained"] = change - sum(parts.values())
    return {
        "actual_kwh": round(actual, 1),
        "expected_kwh": round(float(cur["p50"].sum()), 1),
        "previous_actual_kwh": round(previous, 1),
        "change_kwh": round(change, 1),
        "parts_kwh": {k: round(v, 2) for k, v in parts.items()},
    }


def align(
    cur: pd.DataFrame, prev: pd.DataFrame, lo: datetime, prev_lo: datetime
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The two periods on the same hours from their start, each known in both: a recording gap
    in one must not read as a change in usage."""
    a = cur.dropna(subset=["kwh"]).set_axis(cur.dropna(subset=["kwh"]).index - lo)
    b = prev.dropna(subset=["kwh"]).set_axis(prev.dropna(subset=["kwh"]).index - prev_lo)
    both = a.index.intersection(b.index)
    return a.loc[both], b.loc[both]


async def _period_frame(ctx: Ctx, lo: datetime, hi: datetime) -> pd.DataFrame:
    exp = await expected(ctx.session, ctx.home_id, lo, hi)
    if exp.empty:
        return exp
    exp["kwh"] = (await hourly_actual(ctx.session, ctx.home_id, lo, hi)).reindex(exp.index)
    return exp


async def explain_usage(ctx: Ctx, period: str = "cycle") -> Outcome:
    now = ctx.now or datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    local = now.astimezone(ICT)
    midnight = datetime(local.year, local.month, local.day, tzinfo=ICT).astimezone(UTC)
    if period == "today":
        span, lo = hour - midnight, midnight
        prev_lo = lo - timedelta(days=1)
    elif period == "week":
        span, lo = timedelta(days=7), midnight - timedelta(days=7)
        prev_lo = lo - span
    else:
        period = "cycle"
        day = await ctx.session.scalar(select(Home.billing_cycle_day).where(Home.id == ctx.home_id))
        start = local.date().replace(day=day or 1)
        if local.date().day < (day or 1):
            start = (start.replace(day=1) - timedelta(days=1)).replace(day=day or 1)
        lo = datetime(start.year, start.month, start.day, tzinfo=ICT).astimezone(UTC)
        span = hour - lo
        prev_start = (start.replace(day=1) - timedelta(days=1)).replace(day=day or 1)
        prev_lo = datetime(
            prev_start.year, prev_start.month, prev_start.day, tzinfo=ICT
        ).astimezone(UTC)
    cur = await _period_frame(ctx, lo, lo + span)
    prev = await _period_frame(ctx, prev_lo, prev_lo + span)
    cur, prev = align(cur, prev, lo, prev_lo) if not (cur.empty or prev.empty) else (cur, prev)
    if cur.empty or prev.empty:
        return Outcome(
            {"error": "no expected-usage model for this home yet (it needs 28 full days)"},
            _vi(ctx, "Chưa có mô hình mức dùng", "No usage model yet"),
        )
    return Outcome(
        data={
            "period": period,
            "from": lo.astimezone(ICT).isoformat(timespec="minutes"),
            "previous_from": prev_lo.astimezone(ICT).isoformat(timespec="minutes"),
            **explain_parts(cur, prev),
        },
        detail=_vi(ctx, "Mô hình mức dùng · công tơ tổng", "Usage model · main meter"),
        tier="estimated",
        sources=["meter", "model"],
        links=["statistics"],
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
        widgets=[CompareWidget(period=period, data=data)] if n else [],
        links=["statistics"],
    )


async def weather(ctx: Ctx) -> Outcome:
    home = await ctx.session.get(Home, ctx.home_id)
    province = await ctx.session.get(Province, home.province_code) if home.province_code else None
    if province is None:  # a demo home: its recording site's weather, as the card shows it
        stored = await stored_weather(
            ctx.session, ctx.home_id, ctx.now or datetime.now(UTC), ctx.lang
        )
        if stored is None:
            return Outcome({"error": "the home has no province set (Settings)"}, "OpenWeather")
        place, w = stored
        province = SimpleNamespace(name=place)
    else:
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
            WeatherWidget(
                temp=round(w.now.temp), feels=round(w.now.feels_like), humidity=w.now.humidity
            )
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
            PeersWidget(you=_f(c.kwh, 1), median=round(median, 1), days=c.days, homes=c.homes)
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
            StandbyWidget(
                watts=[round(w) for _, w in watts],
                kwh=round(kwh_month, 1),
                vnd=round(vnd) if vnd else None,
            )
        ],
        links=["statistics"],
    )


T2S_STREAM = "/api/v1/text2sql/chat/stream"
# text2sql's agent tools, as the steps of query_data the user sees while it runs.
T2S_STEPS = {
    "get_metric": ("Đọc định nghĩa chỉ số", "Read a metric's definition"),
    "get_table": ("Xem mô tả bảng", "Read a table's description"),
    "get_expert_rule": ("Đọc quy tắc", "Read a rule"),
    "get_column_values": ("Tra giá trị cột", "Look up column values"),
    "query_metric": ("Tính chỉ số", "Compute a metric"),
    "run_sql": ("Chạy truy vấn", "Run a query"),
    "make_chart": ("Dựng biểu đồ", "Build a chart"),
    "ask_user": ("Cần hỏi lại", "Needs to ask back"),
}


# text2sql chart types the web draws, by the shape it draws them as; any other → a table.
CHART_TYPES = {
    "line": "line",
    "area": "area",
    "area_stacked": "area",
    "area_stacked_100": "area",
    "bar": "bar",
    "bar_grouped": "bar",
    "bar_horizontal": "bar",
    "lollipop": "bar",
    "pie": "donut",
    "donut": "donut",
    "kpi": "kpi",
}
MAX_CHART_ROWS = 200


def _data_step(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The last query that ran cleanly: the data behind the answer."""
    return next((st for st in reversed(steps) if st.get("sql") and not st.get("error")), {})


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float | Decimal):
        return None
    return float(v) if math.isfinite(v) else None


def _cell(v: Any) -> str | float | None:
    """A table cell: arrays and JSON as text, NaN and infinities (not JSON) as null."""
    if isinstance(v, bool):  # before the number check: a bool is an int in Python
        return str(v).lower()
    if isinstance(v, list | dict):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _drawn_as(spec: dict[str, Any] | None, display: str | None) -> str:
    """The chart type the rows can be drawn as without reshaping them (text2sql's prepare step)."""
    if not spec or display == "none":
        return "table"
    enc = spec.get("encoding") or {}
    measures = enc.get("y") or []
    if (
        spec.get("transform")
        or enc.get("series")
        or not enc.get("x")
        or not measures
        or any(m.get("aggregate", "auto") not in ("auto", "none") for m in measures)
    ):
        return "table"
    return CHART_TYPES.get(spec.get("type"), "table")


def chart_widget(
    steps: list[dict[str, Any]], data: dict[str, Any] | None = None
) -> ChartWidget | None:
    """text2sql's result as a chart widget: its own chart, or the agent's later chart of the same
    result; a table when the rows cannot be drawn as they are."""
    data = _data_step(steps) if data is None else data
    rows = data.get("rows") or []
    if not rows:
        return None
    columns = list(data.get("columns") or [])
    rows = [
        [_cell(r[i] if i < len(r) else None) for i in range(len(columns))]
        for r in rows[:MAX_CHART_ROWS]
    ]
    spec = next(
        (
            st["chart"]
            for st in reversed(steps)
            if st.get("tool") == "make_chart"
            and st.get("chart")
            and st.get("result_id") == data.get("result_id")
        ),
        data.get("chart"),
    )
    table = ChartWidget(type="table", title=None, labels=[], series=[], columns=columns, rows=rows)
    drawn = _drawn_as(spec, data.get("display"))
    if drawn == "table":
        return table.model_copy(update={"title": (spec or {}).get("title")})
    enc = spec["encoding"]
    fields = [enc["x"].get("field"), *(m.get("field") for m in enc["y"])]
    if any(f not in columns for f in fields):
        return table
    x = columns.index(fields[0])
    labels = ["" if r[x] is None else str(r[x]) for r in rows]
    if len(set(labels)) < len(labels):  # repeated x: drawing would need text2sql's aggregation
        return table
    return table.model_copy(
        update={
            "type": drawn,
            "title": spec.get("title"),
            "labels": labels,
            "series": [
                ChartSeries(
                    label=m.get("label") or m["field"],
                    unit=(m.get("format") or {}).get("unit"),
                    values=[_num(r[columns.index(m["field"])]) for r in rows],
                )
                for m in enc["y"]
            ],
        }
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
    }
    status, answer, steps = "error", "", []
    try:
        async with (
            httpx.AsyncClient(base_url=settings.text2sql_url, timeout=120) as client,
            client.stream("POST", T2S_STREAM, json=body, headers=headers) as res,
        ):
            if res.status_code != 200:
                await res.aread()
                return Outcome({"error": f"text2sql answered {res.status_code}"}, "text2sql")
            event = None
            async for line in res.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                    continue
                if not line.startswith("data: "):
                    continue
                d = json.loads(line[6:])
                if event == "tool_started":
                    vi, en = T2S_STEPS.get(d.get("tool"), (d.get("tool"), d.get("tool")))
                    ctx.report(_vi(ctx, vi, en), d.get("subject") or "")
                elif event == "tool":
                    steps.append(d)
                elif event == "done":
                    status, answer = d.get("status", "error"), d.get("answer") or ""
    except httpx.HTTPError:
        return Outcome({"error": "text2sql is unreachable"}, "text2sql")
    last = _data_step(steps)
    chart = chart_widget(steps, last)
    sql, columns, rows = last.get("sql"), last.get("columns", []), last.get("rows", [])
    return Outcome(
        data={
            "status": status,
            "columns": columns,
            "rows": rows[:MAX_ROWS_TO_LLM],
            "row_count": last.get("row_count", len(rows)),
            "summary": answer,
        },
        detail=_vi(ctx, "Truy vấn chỉ đọc dữ liệu nhà bạn", "Read-only query of your home's data"),
        tier="estimated",
        sources=["meter"],
        widgets=[chart] if chart else [],
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
            PlanWidget(
                id=str(plan.id),
                tasks=[PlanTask(label=t["label"], detail=t["detail"]) for t in tasks],
                kwh=kwh,
                vnd=vnd,
                status="proposed",
            )
        ],
    )


T2S_CHAT = "/api/v1/text2sql/chat"
WATCH_METRICS = (
    "bill_vnd",
    "bill_kwh",
    "forecast_vnd",
    "today_kwh",
    "power_w",
    "device_kwh_today",
    "custom",
    "device_on",
    "device_off",
    "device_run_min",
    "device_power_w",
)


async def _one_number_sql(ctx: Ctx, question: str) -> tuple[str | None, str | None]:
    """(SQL, None) of the last query text2sql ran cleanly for `question`, or (None, why)."""
    if not settings.text2sql_connection_id:
        return None, "custom watches are not configured"
    token = ScopeToken(home_id=ctx.home_id)
    ctx.session.add(token)
    await ctx.session.commit()  # text2sql reads it from its own connection
    headers = (
        {"X-Service-Key": settings.text2sql_service_key} if settings.text2sql_service_key else {}
    )
    body = {
        "connection_id": settings.text2sql_connection_id,
        "question": f"{question[:400]} (một con số duy nhất, một dòng)",
        "scope_token": str(token.token),
    }
    try:
        async with httpx.AsyncClient(base_url=settings.text2sql_url, timeout=120) as client:
            res = await client.post(T2S_CHAT, json=body, headers=headers)
    except httpx.HTTPError:
        return None, "text2sql is unreachable"
    if res.status_code != 200:
        return None, f"text2sql answered {res.status_code}"
    out = res.json()
    if out.get("clarification_question"):
        return None, f"needs clarification: {out['clarification_question']}"
    steps = [st for a in out.get("answers", []) for st in a.get("steps", [])]
    last = next((st for st in reversed(steps) if st.get("sql") and not st.get("error")), None)
    return (last["sql"], None) if last else (None, "text2sql found no query for it")


def _watch_view(ctx: Ctx, w) -> dict[str, Any]:
    return {
        "watch_id": str(w.id),
        "label": w.label,
        "condition": f"{'>' if w.op == 'gt' else '<'} {_f(w.threshold, 3)} {w.unit}".strip(),
        "value_last_checked": _f(w.last_value, 3),
        "status": w.status,
        "checks_every_minutes": w.every_s // 60,
        # The last day watched: an end at local midnight belongs to the day before.
        "last_day": str((w.ends_at - timedelta(microseconds=1)).astimezone(ICT).date()),
    }


async def create_watch_tool(
    ctx: Ctx,
    metric: str,
    op: str,
    threshold: float,
    label: str,
    device: str | None = None,
    question: str | None = None,
    unit: str | None = None,
    ends_on: str | None = None,
    repeat: bool = True,
) -> Outcome:
    trace = _vi(ctx, "Đặt cảnh báo theo yêu cầu", "Set a requested alert")
    if ctx.user_id is None:
        return Outcome({"error": "no user to notify"}, trace)
    try:
        end = date.fromisoformat(ends_on) if ends_on else None
    except ValueError:
        return Outcome({"error": "ends_on must be YYYY-MM-DD"}, trace)
    device_id, sql = None, None
    if metric.startswith("device_"):
        rows = (
            await ctx.session.execute(
                select(Device.id, Device.name).where(Device.home_id == ctx.home_id)
            )
        ).all()
        hits = [r for r in rows if (device or "").strip().lower() in r.name.lower()]
        if not device or len(hits) != 1:
            return Outcome(
                {"error": "name exactly one device", "devices": [r.name for r in rows]}, trace
            )
        device_id = hits[0].id
    if metric == "custom":
        if not question:
            return Outcome({"error": "a custom watch needs its question"}, trace)
        ctx.report(_vi(ctx, "Dựng truy vấn theo dõi", "Build the watch query"), question[:120])
        sql, why = await _one_number_sql(ctx, question)
        if sql is None:
            return Outcome({"error": why}, trace)
    try:
        w, value = await create_watch(
            ctx.session,
            ctx.user_id,
            ctx.home_id,
            metric="sql" if metric == "custom" else metric,
            op=op,
            threshold=float(threshold),
            label=label,
            now=ctx.now,
            utterance=ctx.question,
            unit=unit,
            device_id=device_id,
            sql=sql,
            ends_on=end,
            repeat=repeat,
        )
        await ctx.session.commit()  # the reply says it is saved
    except WatchError as e:
        await ctx.session.rollback()
        return Outcome({"error": e.code, "detail": str(e), "value_now": _f(e.value, 3)}, trace)
    except Exception:  # a custom query that does not run (syntax, permissions, timeout)
        log.warning("watch query failed", exc_info=True)
        await ctx.session.rollback()
        return Outcome({"error": "the query for this watch does not run; rephrase it"}, trace)
    return Outcome(
        data={"saved": True, **_watch_view(ctx, w), "value_now": _f(value, 3)},
        detail=trace,
        widgets=[
            WatchWidget(
                id=str(w.id),
                label=w.label,
                op=w.op,
                threshold=float(w.threshold),
                unit=w.unit,
                value=_f(value, 3),
                ends_at=w.ends_at,
            )
        ],
        tier="estimated"
        if metric in ("device_kwh_today", "forecast_vnd", "custom")
        else "measured",
        sources=["tariff", "meter"] if metric in ("bill_vnd", "forecast_vnd") else ["meter"],
        sql=sql,
    )


async def list_watches_tool(ctx: Ctx) -> Outcome:
    if ctx.user_id is None:
        return Outcome({"error": "no user"}, "tb_watch")
    ws = await list_watches(ctx.session, ctx.user_id, ctx.home_id)
    return Outcome(
        data={"watches": [_watch_view(ctx, w) for w in ws[:20]]},
        detail=_vi(ctx, "Các cảnh báo bạn đã đặt", "Alerts you set"),
    )


async def cancel_watch_tool(ctx: Ctx, watch_id: str) -> Outcome:
    trace = _vi(ctx, "Huỷ cảnh báo", "Cancel an alert")
    try:
        wid = uuid.UUID(watch_id)
    except ValueError:
        return Outcome({"error": "unknown watch_id; call list_watches"}, trace)
    if ctx.user_id is None or not await cancel_watch(ctx.session, ctx.user_id, ctx.home_id, wid):
        return Outcome({"error": "unknown watch_id; call list_watches"}, trace)
    await ctx.session.commit()
    return Outcome({"cancelled": True, "watch_id": watch_id}, trace)


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
    "device_forecast": (
        device_forecast,
        _fn(
            "device_forecast",
            "Each device's (or one device's) kWh and VND for the next 7 days and to the cycle's "
            "end, its range, what drives it, how certain it is (tried on past days) and priced "
            "advice to use it better.",
            {"device": {"type": "string", "description": "part of the device's name"}},
        ),
    ),
    "explain_usage": (
        explain_usage,
        _fn(
            "explain_usage",
            "Why usage was high or low: actual vs the model's expectation and the change from "
            "the previous period split by weather, calendar, routine and trend.",
            {"period": {"type": "string", "enum": ["today", "week", "cycle"]}},
            ["period"],
        ),
    ),
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
    "create_watch": (
        create_watch_tool,
        _fn(
            "create_watch",
            "Save an alert the user asks for ('tell me when this month's bill passes 1 million'): "
            "the system checks it on its own and notifies the user when it crosses: by default "
            "again each day, billing cycle or device run (repeat=false only when the user wants "
            "to be told just once). "
            "metric: bill_vnd / bill_kwh = the running billing cycle so far (what 'this month' "
            "means for the bill), forecast_vnd = the cycle's bill at its end, today_kwh, power_w "
            "= power right now, device_kwh_today (+ device name), per device run (+ device name): "
            "device_on / device_off (each time it turns on / off; threshold 0), device_run_min "
            "(a run longer than threshold minutes), device_power_w (a run above threshold W), "
            "custom (+ question: a "
            "precise question about this home's data whose answer is ONE number). threshold in "
            "the metric's unit (VND, kWh, W); 1 triệu = 1000000. ends_on only if the user names "
            "an end. If the threshold is missing, ask the user instead of calling this. "
            "Afterwards say in one sentence what you will watch, the threshold, the value now "
            "and the last day watched.",
            {
                "metric": {"type": "string", "enum": list(WATCH_METRICS)},
                "op": {"type": "string", "enum": ["gt", "lt"]},
                "threshold": {"type": "number"},
                "label": {
                    "type": "string",
                    "maxLength": 80,
                    "description": "only what is measured, short, in the user's language, "
                    "without the condition: 'Tiền điện tháng này', not '... vượt 1 triệu'",
                },
                "device": {"type": "string"},
                "question": {"type": "string", "maxLength": 400},
                "unit": {"type": "string", "description": "custom only: the number's unit"},
                "ends_on": {"type": "string", "description": "YYYY-MM-DD, last day watched"},
                "repeat": {"type": "boolean", "description": "default true"},
            },
            ["metric", "op", "threshold", "label"],
        ),
    ),
    "list_watches": (
        list_watches_tool,
        _fn("list_watches", "The alerts the user asked to be watched, active first."),
    ),
    "cancel_watch": (
        cancel_watch_tool,
        _fn(
            "cancel_watch",
            "Stop watching one alert the user set (its watch_id from list_watches).",
            {"watch_id": {"type": "string"}},
            ["watch_id"],
        ),
    ),
}
SPECS = [spec for _, spec in TOOLS.values()]


# Tools that change the home's shared state (a watch, a plan): never for a read-only demo viewer.
WRITES = {"create_watch", "propose_plan"}


async def run_tool(ctx: Ctx, name: str, args: dict[str, Any]) -> tuple[Outcome, bool, int]:
    """(outcome, ok, ms). A bad call or a failing tool gives the model an error, not the user a
    500; the failure is logged."""
    if ctx.read_only and name in WRITES:
        error = "this is a read-only demo home: say alerts and plans cannot be saved here"
        return Outcome({"error": error}, name), False, 0
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
