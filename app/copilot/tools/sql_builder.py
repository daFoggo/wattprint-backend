"""QueryGoal -> one SELECT as a sqlglot tree, and the guard every generated query goes through.

Values never enter the SQL text: each one is a positional parameter ($1, $2, ...), the form
asyncpg takes. Local days become UTC bounds here, in Python.
"""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import sqlglot
from sqlglot import exp

from ..agents.state import QueryGoal
from .catalog import (
    ALLOWED_TABLES,
    CYCLE_MEASURES,
    FUNCTIONS,
    MAX_ROWS,
    MEASURES,
    kind_for,
    view_for,
)


class UnsafeSqlError(ValueError):
    pass


def local_midnight(day: dt.date, tz: str) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(0), ZoneInfo(tz)).astimezone(dt.UTC)


def period_minutes(goal: QueryGoal) -> int:
    days = (goal.end - goal.start).days + 1
    return days * 1440 * (2 if goal.compare_to == "previous_period" else 1)


def build(goal: QueryGoal, tz: str) -> tuple[str, list[Any]]:
    """The five steps of the spec: view, measure, comparison, grouping, filters."""
    if goal.source == "best":
        raise ValueError("resolve source 'best' (plug coverage) before building")
    params: list[Any] = []

    def param(value: Any) -> exp.Parameter:
        params.append(value)
        return exp.Parameter(this=exp.Literal.number(len(params)))

    cycles = goal.measure in CYCLE_MEASURES
    time_col = "start_ts" if cycles else "bucket"
    # 1. the view
    if cycles:
        v = exp.to_table("copilot_ro.device_cycle").as_("v")
    else:
        v = exp.to_table(view_for(goal.source, goal.grain, goal.group_by)).as_("v")
    # 2. the measure, aggregation fixed by the catalog
    column, agg, divide, unit = MEASURES[goal.measure]
    value: exp.Expression = (
        exp.Count(this=exp.Star()) if column == "*" else exp.func(agg, exp.column(column, "v"))
    )
    if divide:
        value = exp.Div(this=value, expression=exp.Literal.number(divide))
    value = exp.func("ROUND", exp.cast(value, "numeric"), exp.Literal.number(2))
    value_name = f"{goal.measure}_{unit.lower()}"

    tz_param: list[exp.Parameter] = []

    def local() -> exp.AtTimeZone:
        """The bucket in the home's timezone; its parameter exists only once it is used."""
        if not tz_param:
            tz_param.append(param(tz))
        return exp.AtTimeZone(this=exp.column(time_col, "v"), zone=tz_param[0].copy())

    select = exp.select().from_(v)
    dims: list[exp.Expression] = []

    # 3. comparison: one query over both periods, labelled
    days = (goal.end - goal.start).days + 1
    start = local_midnight(goal.start, tz)
    end = local_midnight(goal.end + dt.timedelta(days=1), tz)
    lower = start
    if goal.compare_to == "previous_period":
        lower = local_midnight(goal.start - dt.timedelta(days=days), tz)
        dims.append(
            exp.Case()
            .when(exp.GTE(this=exp.column(time_col, "v"), expression=param(start)),
                  exp.Literal.string("current"))
            .else_(exp.Literal.string("previous"))
            .as_("period")
        )
    # 4. grouping
    if goal.grain in ("day", "week", "month"):
        trunc = exp.func("DATE_TRUNC", exp.Literal.string(goal.grain), local())
        dims.append(exp.cast(trunc, "date").as_(goal.grain))
    elif goal.grain == "hour":
        dims.append(exp.func("DATE_TRUNC", exp.Literal.string("hour"), local()).as_("hour"))
    if goal.group_by == "hour_of_day":
        dims.append(exp.Extract(this=exp.var("HOUR"), expression=local()).as_("hour_of_day"))
    elif goal.group_by == "weekday":
        dims.append(exp.Extract(this=exp.var("ISODOW"), expression=local()).as_("weekday"))
    if goal.group_by == "device" or goal.target == "devices":
        # the only join: device names (the views already carry device_id and kind)
        select = select.join(
            exp.to_table("copilot_ro.device").as_("d"),
            on=exp.EQ(this=exp.column("id", "d"), expression=exp.column("device_id", "v")),
        )
        dims.append(exp.column("name", "d").as_("device"))

    outputs = [*dims, value.as_(value_name)]
    if not cycles:
        outputs.append(exp.func("SUM", exp.column("covered_minutes", "v")).as_("covered_minutes"))
    select = select.select(*outputs)

    # 5. filters: which series, which devices, which local days
    conditions: list[exp.Expression] = []
    if not cycles:
        kind = kind_for(goal.source, goal.target, goal.group_by)
        conditions.append(exp.EQ(this=exp.column("kind", "v"), expression=param(kind)))
    conditions += [
        exp.GTE(this=exp.column(time_col, "v"), expression=param(lower)),
        exp.LT(this=exp.column(time_col, "v"), expression=param(end)),
    ]
    if goal.target == "devices":
        ids = [param(device_id) for device_id in goal.device_ids]
        conditions.append(exp.In(this=exp.column("device_id", "v"), expressions=ids))
    select = select.where(exp.and_(*conditions))

    if dims:
        select = select.group_by(*[exp.column(d.alias) for d in dims])
    if goal.order:
        desc = goal.order == "desc"
        select = select.order_by(exp.Ordered(this=exp.column(value_name), desc=desc))
    elif dims:
        select = select.order_by(*[exp.column(d.alias) for d in dims])
    select = select.limit(min(goal.top_n or MAX_ROWS, MAX_ROWS))
    return select.sql(dialect="postgres", pretty=True), params  # pretty: users read it


def unit_of(goal: QueryGoal) -> str:
    return MEASURES[goal.measure][3]


_FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Command, exp.Set, exp.Create,
              exp.Drop, exp.Alter, exp.Into, exp.Lock, exp.TruncateTable, exp.Copy)


def check_text(sql: str, node: str) -> exp.Select:
    """Parse and refuse anything but one bounded SELECT over the node's allowed tables."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSqlError(f"not parseable: {exc}") from None
    if len(statements) != 1:
        raise UnsafeSqlError(f"exactly one statement allowed, got {len(statements)}")
    root = statements[0]
    if not isinstance(root, exp.Select):
        raise UnsafeSqlError(f"only SELECT is allowed, got {root.key.upper()}")
    for part in root.walk():
        if isinstance(part, _FORBIDDEN):
            raise UnsafeSqlError(f"{part.key.upper()} is not allowed")
    ctes = {cte.alias_or_name for cte in root.find_all(exp.CTE)}
    for cte in root.find_all(exp.CTE):
        if not isinstance(cte.this, exp.Select):
            raise UnsafeSqlError("a CTE must be a SELECT")
    allowed = ALLOWED_TABLES[node]
    for table in root.find_all(exp.Table):
        name = f"{table.db}.{table.name}" if table.db else table.name
        if not table.db and name in ctes:
            continue
        if name not in allowed:
            raise UnsafeSqlError(f"table {name} is not allowed here")
    for func in root.find_all(exp.Func):
        if isinstance(func, (exp.Binary, exp.Connector, exp.Predicate, exp.Unary)):
            continue  # operators (AND, ->>, ...), not calls
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).upper()
        if name not in FUNCTIONS:
            raise UnsafeSqlError(f"function {name} is not allowed")
    limit = root.args.get("limit")
    if limit is None:
        raise UnsafeSqlError("a LIMIT is required")
    bound = limit.expression
    if not (isinstance(bound, exp.Literal) and bound.is_int and int(bound.name) <= MAX_ROWS):
        raise UnsafeSqlError(f"LIMIT must be a number up to {MAX_ROWS}")
    return root
