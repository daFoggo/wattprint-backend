"""query_usage: the safe Text2SQL path (validate the goal, build one SELECT, check, run)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from ...agents.state import Candidate, Decision, Grain, GroupBy, Measure, Source
from ...skills import answer_facts, query_planning
from .. import db_connector as db
from .. import home_data
from .. import sql_builder as sql
from ..registry import RunContext, handler


class QueryUsageArgs(BaseModel):
    device_ids: list[str] = Field(default=[], description="ids of the home's devices from the "
                                  "linked terms; empty = the whole home")
    device_type_codes: list[str] = Field(default=[], description="device type codes from the "
                                         "linked terms (the home's devices of that type)")
    start: dt.date | None = Field(default=None, description="first local day, inclusive")
    end: dt.date | None = Field(default=None, description="last local day, inclusive")
    measure: Measure | None = Field(default=None, description="energy (kWh, default), "
                                    "average_power or peak_power (W), cycles or cycle_energy")
    source: Source | None = Field(default=None, description="measured (plug or main meter), "
                                  "estimated (NILM); empty = best")
    grain: Grain = Field(default="none", description="none = one total; day/week/month/hour "
                         "for a breakdown")
    group_by: GroupBy = Field(default="none", description="device for 'which appliance', "
                              "hour_of_day, weekday")
    compare_to: Literal["none", "previous_period"] = "none"
    order: Literal["desc", "asc"] | None = Field(default=None, description="desc with top_n "
                                                 "for 'most', asc for 'least'")
    top_n: int | None = Field(default=None, ge=1, le=1000)
    unclear: bool = Field(default=False, description="true when the question points at an "
                          "appliance it does not name and nothing in the history says which")
    unmatched: list[str] = Field(default=[], description="words naming an appliance that "
                                 "matched no linked term")
    assumptions: list[str] = Field(default=[], description="defaults you assumed, in the "
                                   "question's language")


def _known(rc: RunContext, device_ids: list[str]) -> list[Candidate]:
    """The linked terms, plus the home's own devices a preset (or the history) names."""
    linked = {d for c in rc.terms for d in c.device_ids}
    names = rc.home.get("devices", {})
    extra = [Candidate(source="device", kind="device", ref=d, phrase=names[d], score=1.0,
                       device_ids=[d], device_names=[names[d]], from_history=True)
             for d in device_ids if d in names and d not in linked]
    return [*rc.terms, *extra]


@handler("query_usage", QueryUsageArgs)
async def query_usage(args: QueryUsageArgs, rc: RunContext) -> dict:
    decision = Decision(intent="unclear" if args.unclear else "data",
                        **args.model_dump(exclude={"unclear"}))
    out = query_planning.validate(decision, _known(rc, args.device_ids), rc.home, rc.today,
                                  rc.lang, rc.question)
    assumptions = out.get("assumptions", [])
    if out["outcome"] == "unclear":
        return {"card": out["clarification"].model_dump(), "data": {"clarification": True},
                "miss": out["clarification"].reason == "unknown_word"}
    if out["outcome"] == "no_device":
        return {"data": {"no_device": out["error"]}, "no_device": out["error"], "miss": True}
    if out["outcome"] != "goal":
        return {"ok": False, "error": out.get("error") or "invalid query", "miss": True}
    goal, note = out["goal"], None
    tz = rc.home["timezone"]
    async with db.copilot_tx(rc.ctx.copilot(), rc.token) as conn:
        if goal.source == "best":
            lo = sql.local_midnight(goal.start, tz)
            hi = sql.local_midnight(goal.end + dt.timedelta(days=1), tz)
            covered = await home_data.plug_coverage(conn, goal.device_ids, lo, hi)
            goal, note = query_planning.resolve_source(goal, covered, rc.lang)
        text, params = sql.build(goal, tz)
        sql.check_text(text, "execute")
        await conn.fetch("EXPLAIN " + text, *params)
        try:
            columns, rows, ms = await db.run(conn, text, params)
        except db.QueryFailedError as exc:
            return {"ok": False, "error": str(exc), "sql": text}
    unit = sql.unit_of(goal)
    value_col = f"{goal.measure}_{unit.lower()}"
    coverage = answer_facts.coverage_of(rows, goal)
    has_data = answer_facts.has_data(rows, value_col)
    facts = (answer_facts.data_facts(goal, rows, value_col, unit, coverage, rc.lang)
             if has_data else [])
    result = {"columns": columns, "rows": rows, "sql": text, "unit": unit, "coverage": coverage,
              "source": goal.source}
    return {
        "data": {"rows": rows[:50], "unit": unit, "coverage": coverage, "source": goal.source,
                 "period": [str(goal.start), str(goal.end)], "assumptions": assumptions,
                 "source_note": note, "latest_data_date": rc.home.get("latest_date")},
        "facts": facts, "no_data": not has_data, "sql": text, "unit": unit, "ms": ms,
        "goal": goal.model_dump(mode="json"), "assumptions": assumptions,
        "api": {"result": result},
    }
