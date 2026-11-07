"""Household and expert rules: a safe fragment of first-order logic over motif instances.

A rule body:
    {"motif": "night_baseline", "window_days": 7,
     "when": {"quantifier": "at_least", "n": 3,
              "where": {"fact": "min_w", "op": ">", "value": 300, "unit": "W"}},
     "then": {"suggest": "standby_hunt", "per": "home"}}

`where` is a comparison {fact, op, value[, unit]}, {"all": [...]}, {"any": [...]} or
{"not": ...}; it may be omitted (true). Every quantifier ranges over the finite instances of one
motif in a bounded window, so a rule compiles to one SELECT over copilot_ro.motif_instance,
which goes through the same guard as generated queries.
"""

import datetime as dt
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Rule
from ..tools import sql_builder as sql
from .advice import TEMPLATES
from .motifs import DEVICE_MOTIFS, FACTS

# Each suggestion kind is written (TEMPLATES) and priced from one motif's facts: a rule may only
# pair a motif with its kind, or the advice text would have nothing to fill in.
KIND_MOTIF = {"standby_hunt": "night_baseline", "high_day_review": "day_above_usual",
              "kettle_refill": "repeat_use", "long_run_check": "long_run",
              "tier_alert": "tier_crossing"}
SUGGEST_KINDS = set(TEMPLATES)
assert SUGGEST_KINDS == set(KIND_MOTIF)
OPS = {">", ">=", "<", "<=", "=", "!="}
FACT_NAME = re.compile(r"[a-z_]+")
MAX_DEPTH = 4


class RuleError(ValueError):
    pass


class When(BaseModel):
    quantifier: Literal["at_least_one", "every", "at_least"]
    n: int | None = Field(None, ge=1, le=100)
    where: dict[str, Any] | None = None


class Then(BaseModel):
    suggest: str
    per: Literal["device", "home"] = "home"


class RuleBody(BaseModel):
    motif: str
    window_days: int = Field(7, ge=1, le=30)
    when: When
    then: Then


def _check_condition(cond: Any, motif: str, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise RuleError("the condition is nested too deeply")
    if not isinstance(cond, dict) or not cond:
        raise RuleError("a condition must be an object")
    if "all" in cond or "any" in cond:
        items = cond.get("all", cond.get("any"))
        if not isinstance(items, list) or not items:
            raise RuleError("'all' / 'any' need a non-empty list")
        for c in items:
            _check_condition(c, motif, depth + 1)
        return
    if "not" in cond:
        _check_condition(cond["not"], motif, depth + 1)
        return
    fact, op, value = cond.get("fact"), cond.get("op"), cond.get("value")
    facts = FACTS[motif]
    if fact not in facts:
        raise RuleError(f"motif {motif} has no fact {fact!r}; facts: {sorted(facts)}")
    if not facts[fact]:
        raise RuleError(f"fact {fact!r} is a label and cannot be compared")
    if op not in OPS:
        raise RuleError(f"unknown operator {op!r}")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RuleError(f"the value of {fact!r} must be a number")
    unit = cond.get("unit")
    if unit is not None and unit != facts[fact]:
        raise RuleError(f"{fact!r} is in {facts[fact]}, not {unit}")


def validate(body: dict[str, Any]) -> RuleBody:
    """Parse and check a rule body; RuleError says what is wrong."""
    try:
        rule = RuleBody.model_validate(body)
    except ValidationError as exc:
        raise RuleError(exc.errors()[0]["msg"] + f" at {exc.errors()[0]['loc']}") from None
    if rule.motif not in FACTS:
        raise RuleError(f"unknown motif {rule.motif!r}; motifs: {sorted(FACTS)}")
    if rule.then.suggest not in SUGGEST_KINDS:
        raise RuleError(f"unknown suggestion kind {rule.then.suggest!r}")
    if KIND_MOTIF[rule.then.suggest] != rule.motif:
        raise RuleError(f"{rule.then.suggest} is advice about {KIND_MOTIF[rule.then.suggest]}, "
                        f"not {rule.motif}")
    if rule.then.per == "device" and rule.motif not in DEVICE_MOTIFS:
        raise RuleError(f"motif {rule.motif} is about the whole home, use per: home")
    if rule.when.quantifier == "at_least" and rule.when.n is None:
        raise RuleError("quantifier at_least needs n")
    if rule.when.where is not None:
        _check_condition(rule.when.where, rule.motif)
    return rule


def _condition_sql(cond: dict[str, Any] | None, params: list[Any]) -> str:
    if cond is None:
        return "TRUE"
    if "all" in cond:
        return "(" + " AND ".join(_condition_sql(c, params) for c in cond["all"]) + ")"
    if "any" in cond:
        return "(" + " OR ".join(_condition_sql(c, params) for c in cond["any"]) + ")"
    if "not" in cond:
        return f"(NOT {_condition_sql(cond['not'], params)})"
    fact, op = cond["fact"], cond["op"]
    # validate() checked both; checked again here because they are written into the SQL text
    if not (isinstance(fact, str) and FACT_NAME.fullmatch(fact)) or op not in OPS:
        raise RuleError(f"bad comparison {fact!r} {op!r}")
    params.append(float(cond["value"]))
    return f"(CAST(facts ->> '{fact}' AS DOUBLE PRECISION) {op} ${len(params)})"


def compile_rule(rule: RuleBody) -> str:
    """One SELECT: $1 = motif, $2 = window start (bound at run time), then the values."""
    params: list[Any] = [rule.motif, None]
    c = _condition_sql(rule.when.where, params)
    per_device = rule.then.per == "device"
    q = rule.when.quantifier
    having = {
        "at_least_one": f"count(*) FILTER (WHERE {c}) >= 1",
        "at_least": f"count(*) FILTER (WHERE {c}) >= {int(rule.when.n or 1)}",
        "every": f"bool_and({c}) AND count(*) > 0",
    }[q]
    text = (
        f"SELECT {'device_id' if per_device else 'CAST(NULL AS UUID) AS device_id'}, "
        f"count(*) FILTER (WHERE {c}) AS hits, array_agg(id) FILTER (WHERE {c}) AS instances "
        "FROM copilot_ro.motif_instance WHERE motif = $1 AND start_ts >= $2 "
        f"{'GROUP BY device_id ' if per_device else ''}HAVING {having} LIMIT 100"
    )
    sql.check_text(text, "evaluate_rules")
    return text


def values_of(rule: RuleBody) -> list[float]:
    params: list[Any] = [None, None]
    _condition_sql(rule.when.where, params)
    return params[2:]


def content_hash(rule: RuleBody) -> str:
    return hashlib.sha256(
        json.dumps(rule.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()


async def evaluate(conn, rule: RuleBody, today: dt.date, tz: str) -> list[dict[str, Any]]:
    """Run one rule on the Copilot connection -> [{device_id, hits, instances: [{id, facts}]}].

    Compiled from the body here, through the guard (the stored compiled_sql is for reading):
    the SQL and its parameters always come from the same code.
    """
    since = sql.local_midnight(today - dt.timedelta(days=rule.window_days), tz)
    rows = await conn.fetch(compile_rule(rule), rule.motif, since, *values_of(rule))
    out = []
    for r in rows:
        found = await conn.fetch(
            "SELECT id::text AS id, facts::text AS facts FROM copilot_ro.motif_instance "
            "WHERE id = ANY($1::uuid[]) ORDER BY start_ts", r["instances"] or [])
        out.append({"device_id": str(r["device_id"]) if r["device_id"] else None,
                    "hits": r["hits"],
                    "instances": [{"id": i["id"], "facts": json.loads(i["facts"])}
                                  for i in found]})
    return out


async def dry_run(conn, rule: RuleBody, today: dt.date, tz: str) -> int:
    """How many instances would have fired the rule in its window."""
    return sum(r["hits"] for r in await evaluate(conn, rule, today, tz))


# Expert rules shared by every home, versioned with the code.
SHARED_RULES: dict[str, dict[str, Any]] = {
    "Tải nền ban đêm cao": {  # a night's base load above 1.5 x the window's median night
        "motif": "night_baseline", "window_days": 7,
        "when": {"quantifier": "at_least_one",
                 "where": {"fact": "ratio", "op": ">", "value": 1.5}},
        "then": {"suggest": "standby_hunt", "per": "home"},
    },
    "Ngày dùng điện cao bất thường": {  # a day above 1.3 x the window's median day
        "motif": "day_above_usual", "window_days": 7,
        "when": {"quantifier": "at_least_one",
                 "where": {"fact": "ratio", "op": ">", "value": 1.3}},
        "then": {"suggest": "high_day_review", "per": "home"},
    },
    "Đun nước nhiều lần liền": {
        "motif": "repeat_use", "window_days": 7,
        "when": {"quantifier": "at_least", "n": 2},
        "then": {"suggest": "kettle_refill", "per": "device"},
    },
    "Thiết bị chạy quá lâu": {
        "motif": "long_run", "window_days": 7,
        "when": {"quantifier": "at_least_one"},
        "then": {"suggest": "long_run_check", "per": "device"},
    },
    "Sắp lên bậc giá cao hơn": {
        "motif": "tier_crossing", "window_days": 30,
        "when": {"quantifier": "at_least_one"},
        "then": {"suggest": "tier_alert", "per": "home"},
    },
}


async def ensure_shared(session: AsyncSession) -> None:
    """Upsert the shared rules; a changed body bumps the version."""
    existing = {r.name: r for r in (await session.execute(
        select(Rule).where(Rule.home_id.is_(None)))).scalars()}
    for name, body in SHARED_RULES.items():
        rule = validate(body)
        digest = content_hash(rule)
        compiled = compile_rule(rule)
        old = existing.get(name)
        if old is not None and old.content_hash == digest and old.compiled_sql == compiled:
            continue
        stmt = insert(Rule).values(
            home_id=None, name=name, motif=rule.motif, body=rule.model_dump(mode="json"),
            suggest_kind=rule.then.suggest, compiled_sql=compiled, content_hash=digest,
        )
        await session.execute(stmt.on_conflict_do_update(
            constraint="uq_rule_home_id",
            set_={"motif": stmt.excluded.motif, "body": stmt.excluded.body,
                  "suggest_kind": stmt.excluded.suggest_kind,
                  "compiled_sql": stmt.excluded.compiled_sql,
                  "content_hash": stmt.excluded.content_hash, "version": Rule.version + 1},
        ))
    await session.commit()
