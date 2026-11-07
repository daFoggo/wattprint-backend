"""Advice: price a pattern, rank the candidates, phrase them with numbers from facts only."""

import datetime as dt
import re
from typing import Any

from .motifs import NIGHT_HOURS, tier_of

# copilot.suggestion_feedback.action values (the table's CHECK) and what each API action does
ACCEPT, REJECT, SNOOZE = "accept", "dislike", "ignore"


FEEDBACK = {"accept": (ACCEPT, "accepted"), "reject": (REJECT, "dismissed"),
            "snooze": (SNOOZE, "dismissed"), "done": ("done", "done")}  # -> (action, status)


def marginal_price(tariff: dict[str, Any], monthly_kwh: float) -> float:
    """VND per kWh of the tier the month ends in, VAT included."""
    tier = tier_of(tariff["tiers"], monthly_kwh)
    return tier["price"] * (1 + tariff["vat_rate"])


def saving_kwh_month(motif: str, facts: list[dict[str, Any]], window_days: int) -> float:
    """Deterministic monthly kWh saved if the pattern stops, from the instances' facts."""
    per_month = 30 / window_days
    if motif == "night_baseline":  # the excess over the night hours only: conservative
        return sum(f["excess_w"] for f in facts) * NIGHT_HOURS / 1000 * per_month
    if motif == "day_above_usual":
        return sum(f["excess_kwh"] for f in facts) * per_month
    if motif == "repeat_use":
        return sum(f["kwh"] * (f["cycles"] - 1) / f["cycles"] for f in facts) * per_month
    if motif == "long_run":
        return sum(f["kwh"] * max(f["minutes"] - f["limit_min"], 0) / f["minutes"]
                   for f in facts) * per_month
    if motif == "tier_crossing":
        return max(f["projected_kwh"] - f["tier_from_kwh"] for f in facts)
    raise ValueError(motif)


SEVERITY = {"night_baseline": "excess_w", "day_above_usual": "excess_kwh",
            "repeat_use": "cycles", "long_run": "minutes", "tier_crossing": "projected_kwh"}


def price(candidate: dict[str, Any], tariff: dict[str, Any], monthly_kwh: float
          ) -> dict[str, Any]:
    facts = [i["facts"] for i in candidate["instances"]]
    kwh = saving_kwh_month(candidate["motif"], facts, candidate["window_days"])
    vnd = kwh * marginal_price(tariff, monthly_kwh)
    key = SEVERITY[candidate["motif"]]
    worst = max(candidate["instances"], key=lambda i: float(i["facts"][key]))
    evidence = {**worst["facts"], "instances": len(facts), "saving_kwh": round(kwh, 1),
                "saving_vnd": round(vnd, -2)}
    return {**candidate, "saving_kwh": round(kwh, 3), "saving_vnd": round(vnd, 0),
            "instance_id": worst["id"], "evidence": evidence}


def rank(priced: list[dict[str, Any]], stats: dict[str, dict[str, int]], keep: int = 3
         ) -> list[dict[str, Any]]:
    """score = saving x chance of acceptance; skip kinds open, snoozed (7 d), rejected 2x (30 d)."""
    best: dict[tuple, dict[str, Any]] = {}
    for c in priced:
        s = stats.get(c["kind"], {})
        if s.get("open") or s.get("snoozed_7d") or s.get("rejected_30d", 0) >= 2:
            continue
        p = (s.get("accepts", 0) + 1) / (s.get("accepts", 0) + s.get("rejects", 0) + 2)
        scored = {**c, "p_accept": round(p, 3), "score": round(c["saving_vnd"] * p, 0)}
        key = (c["kind"], c.get("device_id"))
        if key not in best or scored["score"] > best[key]["score"]:
            best[key] = scored
    return sorted(best.values(), key=lambda c: -c["score"])[:keep]


TEMPLATES: dict[str, tuple[str, str]] = {
    "standby_hunt": ("Tìm thiết bị chạy ngầm ban đêm",
                     "Đêm {night}, công suất nền lên tới {min_w} W so với {median_w} W thường "
                     "ngày. Tìm và tắt thiết bị chạy ngầm có thể tiết kiệm khoảng {saving_vnd} đ "
                     "mỗi tháng."),
    "high_day_review": ("Xem lại ngày dùng điện cao",
                        "Ngày {day} nhà bạn dùng {kwh} kWh, cao hơn mức thường {median_kwh} kWh. "
                        "Giữ các ngày như mức thường giúp tiết kiệm khoảng {saving_vnd} đ mỗi "
                        "tháng."),
    "kettle_refill": ("Đun nước một lần đủ dùng",
                      "{device} được đun {cycles} lần trong {window_min} phút. Đun một lần đủ "
                      "dùng giúp tiết kiệm khoảng {saving_vnd} đ mỗi tháng."),
    "long_run_check": ("{device} chạy lâu bất thường",
                       "{device} chạy {minutes} phút, lâu hơn mức thường {limit_min} phút. Kiểm "
                       "tra chương trình chạy giúp tiết kiệm khoảng {saving_vnd} đ mỗi tháng."),
    "tier_alert": ("Sắp lên bậc giá {tier}",
                   "Với mức dùng hiện tại, tháng này nhà bạn dự kiến dùng {projected_kwh} kWh, "
                   "rơi vào bậc {tier}. Giảm khoảng {cut_kwh_per_day} kWh mỗi ngày để ở bậc dưới."),
}


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _show(name: str, value: Any) -> str:
    if isinstance(value, float | int) and not isinstance(value, bool):
        if name in ("saving_vnd",) or abs(value) >= 1000:
            return f"{value:,.0f}".replace(",", ".")
        return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return dt.date.fromisoformat(value).strftime("%d/%m")
    return str(value)


def fill_placeholders(title: str, body: str, facts: dict[str, Any]) -> tuple[str, str]:
    """Fill {placeholders} from the facts. Any digit outside a placeholder, or an unknown
    placeholder, raises: numbers come from facts, never from the LLM."""
    out = []
    for part in (title, body):
        if re.search(r"\d", _PLACEHOLDER.sub("", part)):
            raise ValueError("the text has a number that is not a placeholder")
        missing = [n for n in _PLACEHOLDER.findall(part) if n not in facts]
        if missing:
            raise ValueError(f"unknown placeholders {missing}")
        out.append(_PLACEHOLDER.sub(lambda m: _show(m.group(1), facts[m.group(1)]), part))
    return out[0], out[1]
