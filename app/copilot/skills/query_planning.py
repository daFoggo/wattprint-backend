"""Decision -> QueryGoal: check the LLM's choice against the candidates, fill the period,
pick the data source. Pure: no database."""

import datetime as dt
import uuid
from typing import Any

from ..agents.state import Candidate, Decision, Option, QueryGoal, Unclear
from ..tools.catalog import PLUG_COVERS

MAX_DAYS = 400


def _label(lang: str, vi: str, en: str) -> str:
    return vi if lang == "vi" else en


def _fmt_day(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def period_text(start: dt.date, end: dt.date) -> str:
    return _fmt_day(start) if start == end else f"{start:%d/%m}–{_fmt_day(end)}"


def validate(decision: Decision, candidates: list[Candidate], home: dict[str, Any],
             today: dt.date, lang: str, question: str = "") -> dict[str, Any]:
    """Decision -> {outcome, goal?, clarification?, error?, assumptions}.

    outcome: goal | cost | advice | unclear | invalid | no_device | other.
    """
    assumptions = list(decision.assumptions)
    if decision.intent == "other":
        return {"outcome": "other", "assumptions": assumptions}
    tracked = home.get("tracked", [])
    devices_of = {c.ref: c for c in candidates if c.kind == "device"}
    types_of = {c.ref: c for c in candidates if c.kind == "device_type"}

    if decision.intent == "unclear":
        named = [c for c in candidates if c.device_ids and not c.from_history]
        if named and len({d for c in named for d in c.device_ids}) == 1:
            c = named[0]
            options = [
                Option(label=_label(lang, f"{c.device_names[0]} dùng bao nhiêu điện",
                                    f"How much the {c.device_names[0]} used"),
                       question=_label(lang, f"{c.device_names[0]} dùng bao nhiêu điện?",
                                       f"How much did the {c.device_names[0]} use?")),
                Option(label=_label(lang, f"Cách tiết kiệm với {c.device_names[0]}",
                                    f"How to save on the {c.device_names[0]}"),
                       question=_label(lang, f"Làm sao tiết kiệm điện với {c.device_names[0]}?",
                                       f"How can I save on the {c.device_names[0]}?")),
            ]
            return {"outcome": "unclear", "assumptions": assumptions,
                    "clarification": Unclear(reason="data_or_advice", options=options)}
        # "which one?" only: an unclear phrase ("that machine") is never saved as a home word
        return {"outcome": "unclear", "assumptions": assumptions,
                "clarification": _pick_device(tracked, lang, [])}

    known = set(devices_of) | {d for c in candidates for d in c.device_ids}
    bad = [i for i in decision.device_ids if i not in known]
    bad += [t for t in decision.device_type_codes if t not in types_of]
    if bad:
        return {"outcome": "invalid", "assumptions": assumptions,
                "error": f"not among the candidates: {bad}"}

    device_ids = list(dict.fromkeys(decision.device_ids))
    for code in decision.device_type_codes:
        c = types_of[code]
        if not c.device_ids:
            return {"outcome": "no_device", "assumptions": assumptions, "error": c.phrase}
        if len(c.device_ids) > 1 and decision.group_by != "device":
            options = [Option(label=n, question=f"{n}: {question}") for n in c.device_names[:3]]
            return {"outcome": "unclear", "assumptions": assumptions,
                    "clarification": Unclear(reason="several_devices", options=options)}
        device_ids += [d for d in c.device_ids if d not in device_ids]

    if not device_ids and decision.intent == "data" and decision.group_by != "device":
        own = [c for c in candidates if not c.from_history]  # what THIS question named
        top = own[0] if own else None
        if top is not None and top.kind == "device_type" and not top.device_ids:
            return {"outcome": "no_device", "assumptions": assumptions, "error": top.phrase}
        if decision.unmatched:
            return {"outcome": "unclear", "assumptions": assumptions,
                    "clarification": _pick_device(tracked, lang, decision.unmatched)}

    latest = dt.date.fromisoformat(home["latest_date"]) if home.get("latest_date") else None
    start, end = decision.start, decision.end
    if start is None and end is None:
        end = min(latest or today - dt.timedelta(days=1), today)
        start = end - dt.timedelta(days=6)
        assumptions.append(_label(lang, f"7 ngày gần nhất có dữ liệu ({period_text(start, end)})",
                                  f"the last 7 days with data ({period_text(start, end)})"))
    elif start is None:
        start = end
    elif end is None:
        end = max(start, min(latest or today, today))
    if start > end:
        start, end = end, start
    if end > today:
        return {"outcome": "invalid", "assumptions": assumptions,
                "error": f"end {end} is after today {today}"}
    if (end - start).days + 1 > MAX_DAYS:
        return {"outcome": "invalid", "assumptions": assumptions,
                "error": f"the period is longer than {MAX_DAYS} days"}

    measure = decision.measure or "energy"
    if measure in ("cycles", "cycle_energy") and not device_ids:
        return {"outcome": "invalid", "assumptions": assumptions,
                "error": "cycles need a device"}
    target = "devices" if device_ids else "whole_home"
    source = decision.source or "best"
    if target == "whole_home" and decision.group_by == "device":
        source = "estimated" if source == "best" else source
    elif target == "whole_home":
        source = "measured"  # the main meter
        if not any(not c.from_history for c in candidates) and decision.intent == "data":
            assumptions.append(_label(lang, "cả nhà", "the whole home"))
    # a breakdown stays in time order unless the question asks for the top / bottom N
    order = decision.order if decision.top_n else None
    goal = QueryGoal(
        measure=measure, target=target, device_ids=[uuid.UUID(d) for d in device_ids],
        source=source, start=start, end=end, grain=decision.grain, group_by=decision.group_by,
        compare_to=decision.compare_to, order=order, top_n=decision.top_n,
    )
    outcome = {"data": "goal", "cost": "cost", "advice": "advice"}[decision.intent]
    return {"outcome": outcome, "goal": goal, "assumptions": assumptions}


def _pick_device(tracked: list[dict], lang: str, words: list[str]) -> Unclear:
    word = words[0] if words else None
    options = []
    for d in tracked[:4]:
        term = None
        if word:
            term = {"phrase": word, "kind": "device", "target": {"device_id": d["id"]}}
        options.append(Option(label=d["name"], term=term,
                              question=_label(lang, f"{d['name']} dùng bao nhiêu điện?",
                                              f"How much did the {d['name']} use?")))
    return Unclear(reason="unknown_word" if word else "which_device", options=options)


def resolve_source(goal: QueryGoal, covered: dict[str, int], lang: str) -> tuple[QueryGoal, str]:
    """Source 'best': the plugs when they cover >= 95% of the period, else the NILM estimate."""
    minutes = ((goal.end - goal.start).days + 1) * 1440
    plugs = all(m >= PLUG_COVERS * minutes for m in covered.values()) and bool(covered)
    source = "measured" if plugs else "estimated"
    note = (_label(lang, "số đo từ ổ cắm thông minh", "measured by the smart plug") if plugs else
            _label(lang, "ước tính NILM vì ổ cắm đo không phủ đủ khoảng thời gian",
                   "NILM estimate: the plug does not cover the period"))
    return goal.model_copy(update={"source": source}), note
