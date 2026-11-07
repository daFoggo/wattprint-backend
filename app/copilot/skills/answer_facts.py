"""What the answer shows: the facts read out of the rows, and the answer without an LLM."""

import datetime as dt
from typing import Any

from ..agents.state import Fact, QueryGoal
from ..tools import sql_builder as sql
from .query_planning import period_text

_MEASURE = {
    "energy": ("Điện năng", "Energy"), "average_power": ("Công suất trung bình", "Average power"),
    "peak_power": ("Công suất đỉnh", "Peak power"), "cycles": ("Số lần chạy", "Runs"),
    "cycle_energy": ("Điện năng các lần chạy", "Energy of the runs"),
}


def _num(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:,.2f}".rstrip("0").rstrip(".") if abs(x) < 1000 else f"{x:,.0f}"


def _dim(column: str, value: Any) -> str:
    if column == "hour_of_day":
        return f"{int(float(value)):02d}:00"
    if column in ("day", "week", "month") and isinstance(value, str):
        return dt.date.fromisoformat(value[:10]).strftime("%d/%m")
    if column == "period":
        return {"current": "kỳ này", "previous": "kỳ trước"}.get(value, str(value))
    return str(value)


def coverage_of(rows: list[dict], goal: QueryGoal) -> float | None:
    """Share of the period's minutes the result covers (None when rows are a top-n cut)."""
    if goal.measure in ("cycles", "cycle_energy") or goal.top_n or not rows:
        return None
    if "covered_minutes" not in rows[0]:
        return None
    series = max(len(goal.device_ids), 1) if goal.target == "devices" else (
        len({r.get("device") for r in rows}) if goal.group_by == "device" else 1)
    if goal.compare_to == "previous_period":  # the weaker period, not the pooled share
        minutes = sql.period_minutes(goal) / 2 * series
        per: dict[Any, float] = {}
        for r in rows:
            per[r.get("period")] = per.get(r.get("period"), 0) + (r.get("covered_minutes") or 0)
        return round(min(min(per.values()) / minutes, 1.0), 4) if minutes and per else None
    minutes = sql.period_minutes(goal) * series
    covered = sum((r.get("covered_minutes") or 0) for r in rows)
    return round(min(covered / minutes, 1.0), 4) if minutes else None


def has_data(rows: list[dict], value_col: str) -> bool:
    return any(r.get(value_col) is not None for r in rows)


def data_facts(goal: QueryGoal, rows: list[dict], value_col: str, unit: str,
               coverage: float | None, lang: str) -> list[Fact]:
    vi = lang == "vi"
    facts: list[Fact] = []
    dims = [c for c in (rows[0].keys() if rows else []) if c not in (value_col, "covered_minutes")]
    if len(rows) <= 2:  # longer results are the app's table; the card keeps the summary
        for r in rows:
            label = (" · ".join(_dim(d, r[d]) for d in dims) if dims
                     else _MEASURE[goal.measure][0 if vi else 1])
            facts.append(Fact(k=label, v=f"{_num(r.get(value_col))} {unit}"))
    elif unit == "kWh" and not goal.top_n and goal.compare_to == "none":
        total = sum(r.get(value_col) or 0 for r in rows)
        facts.append(Fact(k="Tổng" if vi else "Total", v=f"{_num(total)} {unit}"))
    facts.append(Fact(k="Khoảng thời gian" if vi else "Period",
                      v=period_text(goal.start, goal.end)))
    src = {"measured": ("Đo thực tế", "Measured"), "estimated": ("Ước tính NILM", "NILM estimate")}
    src_label = src.get(goal.source, ("", ""))[0 if vi else 1]
    if goal.target == "whole_home" and goal.group_by != "device":
        src_label = "Công tơ tổng" if vi else "Main meter"
    facts.append(Fact(k="Nguồn" if vi else "Source", v=src_label))
    if coverage is not None:
        facts.append(Fact(k="Độ phủ dữ liệu" if vi else "Data coverage", v=f"{coverage:.0%}"))
    if goal.compare_to == "previous_period":
        for r in rows:
            if r.get("covered_minutes") is not None:
                share = r["covered_minutes"] / (sql.period_minutes(goal) / 2)
                facts.append(Fact(k=(f"Độ phủ ({r.get('period')})" if vi
                                     else f"Coverage ({r.get('period')})"), v=f"{share:.0%}"))
    return facts


def _vnd(amount: float) -> str:
    """Vietnamese grouping: 137.386, not 137,386."""
    return f"{amount:,.0f}".replace(",", ".")


def cost_facts(cost: dict[str, Any], lang: str) -> list[Fact]:
    vi = lang == "vi"
    return [
        Fact(k="Điện năng" if vi else "Energy", v=f"{_num(cost['kwh'])} kWh"),
        Fact(k="Thành tiền (gồm VAT)" if vi else "Amount (incl. VAT)",
             v=f"{_vnd(cost['amount'])} đ"),
        Fact(k="Kỳ hoá đơn" if vi else "Billing period",
             v=period_text(dt.date.fromisoformat(cost["period_start"]),
                           dt.date.fromisoformat(cost["period_end"]))),
        Fact(k="Độ phủ dữ liệu" if vi else "Data coverage", v=f"{cost['coverage']:.0%}"),
    ]


def advice_facts(suggestions: list[dict[str, Any]], lang: str) -> list[Fact]:
    month = "/tháng" if lang == "vi" else "/month"
    return [Fact(k=s["title"], v=f"{_vnd(s['expected_amount'] or 0)} đ{month}")
            for s in suggestions]


def template_answer(state: dict[str, Any]) -> str:
    """The answer without an LLM: other / no device / invalid / no data, or the facts read out."""
    vi = state.get("lang", "vi") == "vi"
    outcome = state.get("outcome")
    latest = state.get("home", {}).get("latest_date")
    if outcome == "other":
        return ("Mình chỉ trả lời được các câu hỏi về điện của nhà bạn: mức dùng, chi phí và cách "
                "tiết kiệm." if vi else "I can only answer questions about your home's "
                "electricity: usage, cost and how to save.")
    if outcome == "no_device":
        word = state.get("error") or ""
        return (f"Mình không tìm thấy thiết bị “{word}” trong nhà bạn." if vi
                else f"I can't find a device called “{word}” in your home.")
    if outcome == "invalid" or state.get("error"):
        return ("Mình chưa lấy được số liệu cho câu hỏi này. Bạn thử hỏi cụ thể hơn nhé." if vi
                else "I couldn't get the data for this question. Try asking more precisely.")
    if outcome == "advice" and not state.get("suggestions"):
        return ("Hiện chưa có gợi ý tiết kiệm nào cho nhà bạn." if vi
                else "There are no saving suggestions for your home yet.")
    if outcome == "goal" and not state.get("has_data"):
        tail = ""
        if latest:
            tail = (f" Dữ liệu mới nhất là ngày {latest}." if vi
                    else f" The latest data is {latest}.")
        return ("Không có dữ liệu cho khoảng thời gian này." if vi
                else "There is no data for that period.") + tail
    facts = state.get("facts") or []
    return "; ".join(f"{f.k}: {f.v}" for f in facts)
