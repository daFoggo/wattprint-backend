import logging
import math
import re
import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import and_, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.api import forecast_bill
from app.modules.expect.api import (
    active_bundle,
    device_actual,
    device_level,
    feature_frame,
    hourly_actual,
    predict,
    trusted_device,
)
from app.modules.home.api import Device, Home, HomeMember

from ..models import PLAN_KEYS, SavingsPlan
from ..utils import PlanError

MIN_HOURS = 20  # a day with fewer measured hours is not compared (REFIT misses an hour or two)
MIN_RESIDUALS = 14  # out-of-sample days needed before the spread means anything
MAX_ACTIONS = 3
FREEZE_AFTER_END = timedelta(days=7)  # an ended plan still takes its last days as they complete
# A day of a plan with devices waits this long for NILM to finish it, then freezes without them
# (an outage must not hold the home's result back): a day is frozen once, so early loses them.
NILM_WAIT = timedelta(days=2)
PINNED = ("base_7d", "presence")  # model inputs taken from the home's own recent use
log = logging.getLogger(__name__)
_STAMP = re.compile(r"(\d{14})$")


def trained_on(version: str, tz: ZoneInfo) -> date | None:
    """The local day a home model was trained, from its UTC stamp (`ctx-v3-YYYYMMDDhhmmss`): it
    learnt the days before it, so this is the first day it predicts out-of-sample."""
    m = _STAMP.search(version)
    if not m:
        return None
    return datetime.strptime(m[1], "%Y%m%d%H%M%S").replace(tzinfo=UTC).astimezone(tz).date()


def day_totals(frame: pd.DataFrame, actual: pd.Series, tz: ZoneInfo) -> dict[date, dict[str, Any]]:
    """Per local day with at least 20 measured hours: expected P50 and the meter's kWh over those
    same hours, and how many hours."""
    hours = frame[["p50"]].join(actual.rename("kwh"), how="inner").dropna(subset=["kwh"])
    out: dict[date, dict[str, Any]] = {}
    for ts, r in hours.iterrows():
        d = out.setdefault(ts.tz_convert(tz).date(), {"expected": 0.0, "actual": 0.0, "n": 0})
        d["expected"] += float(r.p50)
        d["actual"] += float(r.kwh)
        d["n"] += 1
    return {k: v for k, v in out.items() if v["n"] >= MIN_HOURS}


def _frozen(t: dict[str, Any], bias: float) -> dict[str, float]:
    return {
        "expected": round(t["expected"] + bias * t["n"] / 24, 4),
        "actual": round(t["actual"], 4),
    }


def freeze_days(
    stored: dict[str, dict[str, Any]],
    totals: dict[date, dict[str, Any]],
    bias: float,
    devices: dict[date, dict[str, dict[str, float]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """The plan's days with the newly complete ones set, each once: its expectation plus the
    model's mean error scaled to the hours measured, and the meter's kWh over those hours; with
    the planned devices' own (`devices`, already frozen) when there are any."""
    devices = devices or {}
    new = {
        day.isoformat(): _frozen(t, bias) | ({"devices": devices[day]} if devices.get(day) else {})
        for day, t in totals.items()
    }
    return {**new, **stored}


def model_error(residuals: list[float]) -> tuple[float | None, float]:
    """A model's out-of-sample daily error: its spread (sigma) and mean (bias); none and 0 under
    14 residuals."""
    if len(residuals) < MIN_RESIDUALS:
        return None, 0.0
    return round(statistics.stdev(residuals), 4), round(statistics.fmean(residuals), 4)


def day_bias(plan: Any, bundle: Any) -> float:
    """The mean daily error to add to a day predicted by `bundle`: the plan's stored one while its
    own model predicts, the refit model's own (its out-of-sample residuals, 0 under 14) after."""
    if bundle.version == plan.model_version:
        return float(plan.bias)
    return model_error(bundle.residuals)[1]


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(), tz)


async def nilm_final(s: AsyncSession, home_id: uuid.UUID) -> datetime | None:
    """Where NILM has finished the home (every bin before it is final), or None where it never ran.
    The source is nilm.services.runner.SOURCE, named here: importing the nilm module loads torch."""
    return await s.scalar(
        text(
            "SELECT c.last_ts FROM public.tb_ingest_checkpoint c JOIN public.tb_series m "
            "USING (series_id) WHERE c.source = 'nilm' AND m.home_id = :h AND m.kind = 'main'"
        ),
        {"h": home_id},
    )


async def _tz(s: AsyncSession, home_id: uuid.UUID) -> ZoneInfo:
    return ZoneInfo(await s.scalar(select(Home.timezone).where(Home.id == home_id)))


async def current_plan(
    s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID
) -> SavingsPlan | None:
    return await s.scalar(
        select(SavingsPlan).where(
            SavingsPlan.user_id == user_id,
            SavingsPlan.home_id == home_id,
            SavingsPlan.status == "active",
        )
    )


def _check_actions(actions: list[dict[str, Any]], devices: set[uuid.UUID], cap: float) -> None:
    if not 1 <= len(actions) <= MAX_ACTIONS:
        raise PlanError("bad_actions", f"a plan has 1 to {MAX_ACTIONS} actions")
    keys = [(a["device_id"], a["key"]) for a in actions]
    if len(set(keys)) != len(keys):
        raise PlanError("bad_actions", "an action is listed twice")
    for a in actions:
        if a["key"] not in PLAN_KEYS:
            raise PlanError("bad_actions", f"unknown action {a['key']}")
        if (a["key"] == "always_on") != (a["device_id"] is None):
            raise PlanError("bad_actions", "only the always-on cut has no device")
        if a["device_id"] is not None and a["device_id"] not in devices:
            raise PlanError("bad_actions", "no such device in this home")
        optional = (a["baseline"], a["watts"])
        numbers = [a["kwh"], a["amount"], *(v for v in optional if v is not None)]
        if not all(math.isfinite(v) and v >= 0 for v in numbers) or a["kwh"] > cap:
            raise PlanError("bad_actions", "an action's numbers are out of range")


@dataclass
class Basis:
    """What a plan started now is measured against: the cycle, its forecast and the home model in
    force with its out-of-sample daily error (`sigma` its spread, null under 14 days; `bias` its
    mean, added to each frozen day)."""

    period_start: date
    period_end: date
    forecast_kwh: Decimal
    model_version: str
    sigma: Decimal | None
    bias: Decimal
    earliest_start: date
    today: date


async def plan_basis(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> Basis:
    """Raises LookupError without a tariff plan, PlanError before the home has a forecast."""
    f = await forecast_bill(s, home_id, now)
    if f is None:
        raise PlanError("no_forecast", "the home needs a week of readings first")
    tz = await _tz(s, home_id)
    bundle = await active_bundle(s, home_id)
    model = bundle.version if bundle else "none"
    sigma, bias = model_error(bundle.residuals if bundle else [])
    return Basis(
        period_start=f.period_start,
        period_end=f.period_end,
        forecast_kwh=f.kwh,
        model_version=model,
        sigma=None if sigma is None else Decimal(str(sigma)),
        bias=Decimal(str(bias)),
        earliest_start=max(f.period_start, trained_on(model, tz) or f.period_start),
        today=now.astimezone(tz).date(),
    )


async def create_plan(
    s: AsyncSession,
    user_id: uuid.UUID,
    home_id: uuid.UUID,
    *,
    start_on: date,
    actions: list[dict[str, Any]],
    now: datetime,
) -> SavingsPlan:
    """Store the plan with what its measurement rests on, derived here (`plan_basis`). The caller
    commits."""
    if await current_plan(s, user_id, home_id):
        raise PlanError("plan_exists", "a plan is already running")
    b = await plan_basis(s, home_id, now)
    if not b.earliest_start <= start_on <= min(b.today, b.period_end):
        raise PlanError(
            "bad_start", f"the start is from {b.earliest_start} to {min(b.today, b.period_end)}"
        )
    devices = set(
        await s.scalars(
            select(Device.id).where(Device.home_id == home_id, Device.deleted_at.is_(None))
        )
    )
    _check_actions(actions, devices, float(b.forecast_kwh))
    plan = SavingsPlan(
        user_id=user_id,
        home_id=home_id,
        start_on=start_on,
        end_on=b.period_end,
        model_version=b.model_version,
        sigma=b.sigma,
        bias=b.bias,
        forecast_kwh=b.forecast_kwh,
        actions=[{**a, "device_id": a["device_id"] and str(a["device_id"])} for a in actions],
        days={},
    )
    try:
        async with s.begin_nested():  # two creates at once: the unique index answers, not a 500
            s.add(plan)
    except IntegrityError as e:
        raise PlanError("plan_exists", "a plan is already running") from e
    try:
        async with s.begin_nested():  # a backdated start shows its days at once
            await freeze_plans(s, home_id, now)
    except Exception:  # the hourly job sets them later; the plan itself is stored
        log.exception("freezing a new plan's days failed", extra={"home_id": str(home_id)})
        await s.refresh(plan)  # the savepoint's rollback expired it; read it back before the reply
    return plan


async def stop_plan(s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID, now: datetime) -> bool:
    plan = await current_plan(s, user_id, home_id)
    if plan is None:
        return False
    plan.status, plan.stopped_at = "stopped", now
    return True


async def pinned_frame(
    s: AsyncSession, home_id: uuid.UUID, start_on: date, days: list[date], now: datetime
) -> pd.DataFrame:
    """The model inputs over `days` (oldest first) with observed weather but the usage-derived
    ones (the 7-day level, the presence routine) as known at `start_on`: live, they follow a
    plan's own lower use within a week and would learn the saving away."""
    tz = await _tz(s, home_id)
    lo, hi = _midnight(days[0], tz), _midnight(days[-1] + timedelta(days=1), tz)
    x = await feature_frame(s, home_id, lo, hi, now)
    start = await feature_frame(s, home_id, lo, hi, _midnight(start_on, tz))
    x[list(PINNED)] = start[list(PINNED)]
    return x


async def measure_days(
    s: AsyncSession,
    home_id: uuid.UUID,
    bundle: Any,
    start_on: date,
    days: list[date],
    now: datetime,
    x: pd.DataFrame | None = None,
) -> dict[date, dict[str, Any]]:
    """`days` predicted by `bundle` from their `pinned_frame` (`x` when the caller has it),
    against the meter. Only days with at least 20 measured hours come back."""
    tz = await _tz(s, home_id)
    x = x if x is not None else await pinned_frame(s, home_id, start_on, days, now)
    lo, hi = x.index[0], x.index[-1] + pd.Timedelta(hours=1)
    totals = day_totals(predict(bundle, x), await hourly_actual(s, home_id, lo, hi), tz)
    return {d: t for d, t in totals.items() if d in days}


async def measure_devices(
    s: AsyncSession, home_id: uuid.UUID, actions: list[dict], start_on: date, x: pd.DataFrame
) -> dict[date, dict[str, dict[str, float]]]:
    """Each planned device with a trusted model (it beat the weekday-hour mean) over `x`'s days,
    as the home is measured: its model with observed weather but its own 7-day level and the
    home's presence as known at `start_on`, plus its mean error, against NILM's kWh over the same
    measured hours (≥ 20). A device without one is left out: its usual before the plan stands."""
    tz = await _tz(s, home_id)
    lo, hi = x.index[0], x.index[-1] + pd.Timedelta(hours=1)
    out: dict[date, dict[str, dict[str, float]]] = {}
    for did in dict.fromkeys(a["device_id"] for a in actions if a.get("device_id")):
        device = uuid.UUID(did)
        bundle = await active_bundle(s, home_id, device)
        if not trusted_device(bundle):
            continue
        level = await device_level(s, home_id, device, start_on)
        if math.isnan(level):  # no full day before the start: nothing to expect it from
            continue
        xd = x.assign(base_7d=level)
        totals = day_totals(predict(bundle, xd), await device_actual(s, device, lo, hi), tz)
        bias = model_error(bundle.residuals)[1]
        for day, t in totals.items():
            out.setdefault(day, {})[did] = _frozen(t, bias)
    return out


HISTORY_MAX = 12


def _owners(home_id: uuid.UUID):
    return select(HomeMember.user_id).where(
        HomeMember.home_id == home_id, HomeMember.role == "owner"
    )


async def visible_plan(
    s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID, plan_id: uuid.UUID
) -> SavingsPlan | None:
    """One plan of the home the caller may open: theirs, or a home owner's (as in the history)."""
    return await s.scalar(
        select(SavingsPlan).where(
            SavingsPlan.id == plan_id,
            SavingsPlan.home_id == home_id,
            or_(SavingsPlan.user_id == user_id, SavingsPlan.user_id.in_(_owners(home_id))),
        )
    )


async def plan_history(
    s: AsyncSession, user_id: uuid.UUID, home_id: uuid.UUID, now: datetime
) -> list[SavingsPlan]:
    """The home's finished plans, newest start first: the caller's stopped ones (an active one, even
    past its cycle, is the current plan) and the owners' stopped or ended ones (a demo guest is a
    new account each visit, so the demo home's past plans are its owner's)."""
    today = now.astimezone(await _tz(s, home_id)).date()
    owners = _owners(home_id)
    return list(
        await s.scalars(
            select(SavingsPlan)
            .where(
                SavingsPlan.home_id == home_id,
                SavingsPlan.days
                != {},  # stopped before a day was measured: nothing to look back on
                or_(
                    and_(SavingsPlan.user_id == user_id, SavingsPlan.status == "stopped"),
                    and_(
                        SavingsPlan.user_id != user_id,
                        SavingsPlan.user_id.in_(owners),
                        or_(SavingsPlan.status == "stopped", SavingsPlan.end_on < today),
                    ),
                ),
            )
            .order_by(SavingsPlan.start_on.desc())
            .limit(HISTORY_MAX)
        )
    )


async def freeze_plans(s: AsyncSession, home_id: uuid.UUID, now: datetime) -> None:
    """Set each running plan's newly complete days (the insight worker, hourly). A day is predicted
    by the active model with observed weather but the usage-derived inputs (the 7-day level, the
    presence routine) as known at the plan's start: live, they follow the plan's own lower use
    within a week and would learn the saving away."""
    tz = await _tz(s, home_id)
    today = now.astimezone(tz).date()
    plans = (
        await s.scalars(
            select(SavingsPlan).where(
                SavingsPlan.home_id == home_id,
                SavingsPlan.status == "active",
                SavingsPlan.end_on >= today - FREEZE_AFTER_END,
            )
        )
    ).all()
    bundle = await active_bundle(s, home_id) if plans else None
    if bundle is None:
        return
    for plan in plans:
        last = min(plan.end_on, today - timedelta(days=1))
        if any(a.get("device_id") for a in plan.actions):
            final = await nilm_final(s, home_id)
            if final is not None:  # the last day NILM finished, or one past the wait
                done = final.astimezone(tz).date() - timedelta(days=1)
                last = min(last, max(done, today - timedelta(days=1) - NILM_WAIT))
        span = [plan.start_on + timedelta(days=i) for i in range((last - plan.start_on).days + 1)]
        missing = [d for d in span if d.isoformat() not in plan.days]
        if not missing:
            continue
        x = await pinned_frame(s, home_id, plan.start_on, missing, now)
        totals = await measure_days(s, home_id, bundle, plan.start_on, missing, now, x)
        if totals:
            devices = await measure_devices(s, home_id, plan.actions, plan.start_on, x)
            plan.days = freeze_days(plan.days, totals, day_bias(plan, bundle), devices)
