import json
import statistics
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import select, text

from app.database import SessionLocal
from app.modules.insight.services import plans as plans_service
from app.modules.insight.services.plans import day_bias, day_totals, freeze_days, trained_on

ICT = ZoneInfo("Asia/Ho_Chi_Minh")


def _hours(day: str, n: int, p50: float = 0.4, kwh: float = 0.5):
    idx = pd.date_range(pd.Timestamp(day, tz=ICT), periods=n, freq="h").tz_convert(UTC)
    return pd.DataFrame({"p50": p50}, index=idx), pd.Series(kwh, index=idx, dtype=float)


def test_trained_on_reads_the_utc_stamp_as_the_local_day():
    assert trained_on("ctx-v2-20261119031500", ICT) == date(2026, 11, 19)
    # 22:00 UTC on the 18th is 05:00 ICT on the 19th: the 18th was among its training days.
    assert trained_on("ctx-v2-20261118220000", ICT) == date(2026, 11, 19)
    assert trained_on("none", ICT) is None


def test_day_totals_sum_measured_hours_and_drop_thin_days():
    f1, a1 = _hours("2026-11-20", 24)
    a1.iloc[3] = float("nan")  # an hour the meter missed: out of both sums
    f2, a2 = _hours("2026-11-21", 19)  # under 20 measured hours
    t = day_totals(pd.concat([f1, f2]), pd.concat([a1, a2]), ICT)
    assert list(t) == [date(2026, 11, 20)]
    d = t[date(2026, 11, 20)]
    assert d["n"] == 23 and round(d["expected"], 6) == 9.2 and d["actual"] == 11.5


def test_freeze_days_sets_a_day_once_with_the_mean_error_added():
    stored = {"2026-11-20": {"expected": 9.0, "actual": 7.0}}
    totals = {
        date(2026, 11, 20): {"expected": 8.0, "actual": 7.5, "n": 24},  # already set: kept
        date(2026, 11, 21): {"expected": 6.0, "actual": 6.5, "n": 12},
    }
    assert freeze_days(stored, totals, 1.2) == {
        "2026-11-20": {"expected": 9.0, "actual": 7.0},
        "2026-11-21": {"expected": 6.6, "actual": 6.5},  # 1.2 × 12/24 for the hours measured
    }


# --- API: POST/GET/DELETE /api/v1/insights/plans ----------------------------------------------

URL = "/api/v1/insights/plans"


async def _device(home_id):
    async with SessionLocal() as s, s.begin():
        return await s.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'kettle', 'Kettle', 'manual') RETURNING id"
            ),
            {"h": home_id},
        )


def _stub(monkeypatch, today: date):
    async def forecast(s, home_id, now):
        return SimpleNamespace(
            period_start=today - timedelta(days=5),
            period_end=today + timedelta(days=20),
            kwh=Decimal("400"),
        )

    async def bundle(s, home_id):
        stamp = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y%m%d%H%M%S")
        return SimpleNamespace(version=f"ctx-v2-{stamp}", residuals=[1.0, 3.0] * 10)

    monkeypatch.setattr(plans_service, "forecast_bill", forecast)
    monkeypatch.setattr(plans_service, "active_bundle", bundle)


def _action(device_id, key="kettle_fill", **kw):
    return {
        "device_id": str(device_id) if device_id else None,
        "key": key,
        "label": "Chỉ đun lượng nước cần dùng",
        "kwh": 3.4,
        "amount": 12515,
        "baseline": 0.52,
        "watts": None,
    } | kw


async def test_a_viewer_makes_reads_and_stops_a_plan(client, make_member, monkeypatch):
    today = datetime.now(ICT).date()
    _stub(monkeypatch, today)
    me = await make_member("viewer")  # a demo guest: the plan is theirs, not the home's
    device = await _device(me.home_id)
    b = await client.get(f"{URL}/basis", headers=me.headers)
    assert b.status_code == 200, b.text
    assert (
        b.json()["earliest_start"] == (today - timedelta(days=3)).isoformat()
    )  # trained 3 days ago
    assert (
        b.json()["bias"] == 2.0
        and b.json()["period_end"] == (today + timedelta(days=20)).isoformat()
    )
    body = {"start_on": today.isoformat(), "actions": [_action(device)]}

    r = await client.post(URL, json=body, headers=me.headers)
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["end_on"] == (today + timedelta(days=20)).isoformat()
    assert plan["forecast_kwh"] == 400 and plan["model_version"].startswith("ctx-v2-")
    assert plan["sigma"] == round(statistics.stdev([1.0, 3.0] * 10), 4)
    assert plan["bias"] == 2.0 and plan["days"] == []

    assert (await client.post(URL, json=body, headers=me.headers)).status_code == 409
    got = await client.get(f"{URL}/current", headers=me.headers)
    assert got.status_code == 200 and got.json()["id"] == plan["id"]

    housemate = await make_member("member", home_id=me.home_id)  # plans are per person
    assert (await client.get(f"{URL}/current", headers=housemate.headers)).status_code == 404

    assert (await client.delete(f"{URL}/current", headers=me.headers)).status_code == 204
    assert (await client.get(f"{URL}/current", headers=me.headers)).status_code == 404
    assert (await client.delete(f"{URL}/current", headers=me.headers)).status_code == 404


async def test_a_plan_is_checked_before_it_is_stored(client, make_member, monkeypatch):
    today = datetime.now(ICT).date()
    _stub(monkeypatch, today)
    me = await make_member("owner")
    device = await _device(me.home_id)
    other = await make_member("owner")
    foreign = await _device(other.home_id)
    bad = [
        {"start_on": (today + timedelta(days=1)).isoformat(), "actions": [_action(device)]},
        # Before the model's training day: that day would be in-sample.
        {"start_on": (today - timedelta(days=4)).isoformat(), "actions": [_action(device)]},
        {"start_on": today.isoformat(), "actions": []},
        {"start_on": today.isoformat(), "actions": [_action(foreign)]},
        {"start_on": today.isoformat(), "actions": [_action(None)]},  # a device action needs one
        {"start_on": today.isoformat(), "actions": [_action(device, key="always_on")]},
        {"start_on": today.isoformat(), "actions": [_action(device, key="shift_load")]},
        {"start_on": today.isoformat(), "actions": [_action(device, kwh=-1)]},
        {"start_on": today.isoformat(), "actions": [_action(device, kwh=401)]},
        {"start_on": today.isoformat(), "actions": [_action(device)] * 2},
    ]
    for body in bad:
        r = await client.post(URL, json=body, headers=me.headers)
        assert r.status_code == 422, (body, r.text)
    ok = {"start_on": today.isoformat(), "actions": [_action(None, key="always_on", watts=30)]}
    assert (await client.post(URL, json=ok, headers=me.headers)).status_code == 201
    async with SessionLocal() as s:
        n = await s.scalar(
            text("SELECT count(*) FROM public.tb_savings_plan WHERE user_id = :u"),
            {"u": uuid.UUID(str(me.user_id))},
        )
    assert n == 1


# --- freeze_plans (the hourly job) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "residuals", "want"),
    [
        ("ctx-v2-a", [], 7.48),  # the plan's own model: its stored bias 0.48
        ("ctx-v2-b", [0.24] * 14, 7.24),  # after a refit: the new model's own mean error
    ],
)
async def test_freeze_plans_predicts_from_the_start_and_sets_each_day_once(
    make_member, monkeypatch, version, residuals, want
):
    from app.modules.insight.models import SavingsPlan

    now = datetime.now(UTC)
    today = now.astimezone(ICT).date()
    start = today - timedelta(days=3)
    start_midnight = datetime.combine(start, datetime.min.time(), ICT)
    me = await make_member("owner")
    calls = []

    async def bundle(s, home_id):
        return SimpleNamespace(version=version, residuals=residuals)

    async def frame(s, home_id, lo, hi, at):
        calls.append((lo, hi, at))
        idx = pd.date_range(pd.Timestamp(lo), pd.Timestamp(hi), freq="h", inclusive="left")
        pre = at == start_midnight  # usage-derived inputs as known at the plan's start
        return pd.DataFrame(
            {"base_7d": 7.0 if pre else 10.0, "presence": 0.1 if pre else 0.9}, index=idx
        )

    def predict(b, x):
        assert (x["presence"] == 0.1).all()  # the pinned column replaced the live one
        return pd.DataFrame({"p50": x["base_7d"] / 24}, index=x.index)

    async def actual(s, home_id, lo, hi):
        idx = pd.date_range(pd.Timestamp(lo), pd.Timestamp(hi), freq="h", inclusive="left")
        a = pd.Series(0.25, index=idx.tz_convert(UTC), dtype=float)
        thin = idx.tz_convert(ICT).date == today - timedelta(days=2)
        a[thin & (idx.tz_convert(ICT).hour >= 19)] = float("nan")  # 19 measured hours
        return a

    monkeypatch.setattr(plans_service, "active_bundle", bundle)
    monkeypatch.setattr(plans_service, "feature_frame", frame)
    monkeypatch.setattr(plans_service, "predict", predict)
    monkeypatch.setattr(plans_service, "hourly_actual", actual)

    def plan(**kw):
        cols = {
            "user_id": me.user_id,
            "home_id": me.home_id,
            "start_on": start,
            "end_on": today + timedelta(days=10),
            "model_version": "ctx-v2-a",
            "sigma": None,
            "bias": Decimal("0.48"),
            "forecast_kwh": Decimal(400),
            "actions": [],
            "days": {start.isoformat(): {"expected": 99.0, "actual": 1.0}},  # set before: kept
        }
        return SavingsPlan(**(cols | kw))

    housemate = await make_member("member", home_id=me.home_id)
    ended = await make_member("member", home_id=me.home_id)
    async with SessionLocal() as s, s.begin():
        running = plan()
        stopped = plan(status="stopped", user_id=housemate.user_id)
        # Ended more than 7 days ago: no longer looked at.
        old = plan(
            user_id=ended.user_id,
            start_on=today - timedelta(days=40),
            end_on=today - timedelta(days=8),
            days={},
        )
        s.add_all([running, stopped, old])
    async with SessionLocal() as s, s.begin():
        await plans_service.freeze_plans(s, me.home_id, now)
    async with SessionLocal() as s:
        rows = await s.scalars(select(SavingsPlan).where(SavingsPlan.home_id == me.home_id))
        got = {(p.status, p.end_on < today): p.days for p in rows}
    yesterday = (today - timedelta(days=1)).isoformat()
    assert got[("active", True)] == {}
    assert got[("active", False)] == {
        start.isoformat(): {"expected": 99.0, "actual": 1.0},  # kept as first set
        # today − 2 had 19 measured hours: not set; yesterday: pinned level 7 + the day's bias.
        yesterday: {"expected": want, "actual": 6.0},
    }
    assert got[("stopped", False)] == {start.isoformat(): {"expected": 99.0, "actual": 1.0}}
    # Only the days not yet set are predicted, live and as of the start; nothing for today.
    assert {c[2] for c in calls} == {now, start_midnight}
    midnight = datetime.combine(today, datetime.min.time(), ICT)
    assert all(c[0] > start_midnight and c[1] <= midnight for c in calls)


@pytest.mark.parametrize("nilm", ["done", "behind", "down"])
async def test_freeze_plans_sets_each_trusted_device_against_its_own_model(
    client, make_member, monkeypatch, nilm
):
    from app.modules.insight.models import SavingsPlan

    now = datetime.now(UTC)
    today = now.astimezone(ICT).date()
    start = today - timedelta(days=4 if nilm == "down" else 2)
    start_midnight = datetime.combine(start, datetime.min.time(), ICT)
    me = await make_member("owner")
    trusted, weekday, new = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def bundle(s, home_id, device_id=None):
        if device_id is None:
            return SimpleNamespace(version="ctx-v2-a", residuals=[])
        won = device_id in (trusted, new)  # it beat the weekday-hour mean
        bt = {"mae_model": 1.0 if won else 3.0, "mae_base": 2.0}
        return SimpleNamespace(version="dev", residuals=[0.24] * 14, metrics={"backtest": bt})

    async def frame(s, home_id, lo, hi, at):
        idx = pd.date_range(pd.Timestamp(lo), pd.Timestamp(hi), freq="h", inclusive="left")
        pre = at == start_midnight
        return pd.DataFrame(
            {"base_7d": 7.0 if pre else 10.0, "presence": 0.1 if pre else 0.9}, index=idx
        )

    async def level(s, home_id, device_id, day):
        assert day == start  # as known the morning the plan started
        return 2.4 if device_id == trusted else float("nan")  # `new`: no full day before

    def predict(b, x):
        assert (x["presence"] == 0.1).all()
        return pd.DataFrame({"p50": x["base_7d"] / 24}, index=x.index)

    def hourly(kwh):
        async def read(s, owner, lo, hi):
            idx = pd.date_range(pd.Timestamp(lo), pd.Timestamp(hi), freq="h", inclusive="left")
            return pd.Series(kwh, index=idx.tz_convert(UTC), dtype=float)

        return read

    async def nilm_final(s, home_id):
        # Behind: NILM has finished the start day only; yesterday waits for it (not 2 days yet).
        # Down for 10 days: the days past the 2-day wait freeze anyway, the rest still wait.
        back = 1 if nilm == "behind" else 10
        return datetime.combine(today - timedelta(days=back), datetime.min.time(), ICT)

    if nilm != "done":
        monkeypatch.setattr(plans_service, "nilm_final", nilm_final)
    for name, fn in (
        ("active_bundle", bundle),
        ("feature_frame", frame),
        ("device_level", level),
        ("predict", predict),
        ("hourly_actual", hourly(0.25)),
        ("device_actual", hourly(0.05)),
    ):
        monkeypatch.setattr(plans_service, name, fn)

    def action(device_id, key):
        return {
            "device_id": device_id and str(device_id),
            "key": key,
            "label": key,
            "kwh": 1.0,
            "amount": 3000.0,
            "baseline": 1.5 if device_id else 200.0,
            "watts": None if device_id else 40.0,
        }

    async with SessionLocal() as s, s.begin():
        s.add(
            SavingsPlan(
                user_id=me.user_id,
                home_id=me.home_id,
                start_on=start,
                end_on=today + timedelta(days=10),
                model_version="ctx-v2-a",
                sigma=None,
                bias=Decimal("0.48"),
                forecast_kwh=Decimal(400),
                actions=[
                    action(trusted, "kettle_fill"),
                    action(weekday, "fewer_runs"),  # no trusted model: no entry
                    action(new, "fridge_check"),
                    action(None, "always_on"),
                ],
                days={},
            )
        )
    async with SessionLocal() as s, s.begin():
        await plans_service.freeze_plans(s, me.home_id, now)
    yesterday = (today - timedelta(days=1)).isoformat()
    want = {str(trusted): {"expected": 2.64, "actual": 1.2}}  # 2.4 + 0.24, 24 × 0.05
    async with SessionLocal() as s:
        days = (await s.scalar(select(SavingsPlan).where(SavingsPlan.user_id == me.user_id))).days
    r = await client.get(f"{URL}/current", headers=me.headers)
    got = {d["date"]: d["devices"] for d in r.json()["days"]}
    if nilm == "behind":
        assert got == {start.isoformat(): want}
        return
    if nilm == "down":
        assert got == {start.isoformat(): want, (today - timedelta(days=3)).isoformat(): want}
        return
    assert days[yesterday] == {"expected": 7.48, "actual": 6.0, "devices": want}
    assert got == {start.isoformat(): want, yesterday: want}


async def test_nilm_final_is_the_homes_main_series_checkpoint(make_member):
    me = await make_member("owner")
    async with SessionLocal() as s, s.begin():
        series = await s.scalar(
            text(
                "INSERT INTO public.tb_series (home_id, kind, metric, unit) "
                "VALUES (:h, 'main', 'power_w', 'W') RETURNING series_id"
            ),
            {"h": me.home_id},
        )
    async with SessionLocal() as s:
        assert await plans_service.nilm_final(s, me.home_id) is None  # NILM never ran there
    at = datetime(2026, 11, 23, 17, tzinfo=UTC)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_ingest_checkpoint (source, series_id, last_ts) "
                "VALUES ('nilm', :s, :t), ('refit', :s, :t2)"
            ),
            {"s": series, "t": at, "t2": at + timedelta(days=5)},
        )
    async with SessionLocal() as s:
        assert await plans_service.nilm_final(s, me.home_id) == at


async def _plan(user_id, home_id, start: date, end: date, status="stopped"):
    async with SessionLocal() as s, s.begin():
        return await s.scalar(
            text(
                "INSERT INTO public.tb_savings_plan (user_id, home_id, start_on, end_on, "
                "model_version, sigma, bias, forecast_kwh, actions, days, status, stopped_at) "
                "VALUES (:u, :h, :a, :b, 'holdout-x', 3.5, 1.0, 400, CAST(:acts AS jsonb), "
                "CAST(:days AS jsonb), :st, :stopped) RETURNING id"
            ),
            {
                "u": user_id,
                "h": home_id,
                "a": start,
                "b": end,
                "st": status,
                "stopped": datetime.now(UTC) if status == "stopped" else None,
                "acts": '[{"device_id": null, "key": "always_on", "label": "x", "kwh": 5, '
                '"amount": 9000, "baseline": 200, "watts": 40}]',
                "days": json.dumps({start.isoformat(): {"expected": 12.0, "actual": 10.5}}),
            },
        )


async def test_history_lists_finished_plans_of_mine_and_the_owners(client, make_member):
    today = datetime.now(ICT).date()
    owner = await make_member("owner")
    me = await make_member("viewer", home_id=owner.home_id)
    other = await make_member("member", home_id=owner.home_id)
    d = lambda n: today - timedelta(days=n)  # noqa: E731
    owners_old = await _plan(owner.user_id, owner.home_id, d(90), d(61))
    owners_new = await _plan(owner.user_id, owner.home_id, d(60), d(31))
    later = today + timedelta(days=20)
    owners_running = await _plan(owner.user_id, owner.home_id, d(5), later, "active")
    mine_stopped = await _plan(me.user_id, owner.home_id, d(30), d(1))
    # Not stopped, cycle over: still the current plan (its ended view), not history.
    mine_ended = await _plan(me.user_id, owner.home_id, d(29), d(2), "active")
    co_owner = await make_member("owner", home_id=owner.home_id)
    owners_ended = await _plan(co_owner.user_id, owner.home_id, d(100), d(95), "active")
    await _plan(other.user_id, owner.home_id, d(40), d(35))  # a housemate's own plan stays theirs
    blank = await _plan(me.user_id, owner.home_id, d(3), d(3))  # stopped before a day was measured
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("UPDATE public.tb_savings_plan SET days = '{}' WHERE id = :i"), {"i": blank}
        )

    r = await client.get(f"{URL}/history", headers=me.headers)
    assert r.status_code == 200, r.text
    got = r.json()
    want = [mine_stopped, owners_new, owners_old, owners_ended]
    assert [p["id"] for p in got] == [str(i) for i in want]
    assert [p["mine"] for p in got] == [True, False, False, False]
    assert {str(mine_ended), str(blank)}.isdisjoint(p["id"] for p in got)
    day = {"date": d(30).isoformat(), "expected": 12.0, "actual": 10.5, "devices": {}}
    assert got[0]["days"] == [day]
    assert got[0]["stopped_at"] is not None and got[3]["stopped_at"] is None
    assert str(owners_running) not in {p["id"] for p in got}

    # The owner's own view: their running plan is the current one, never history.
    own = (await client.get(f"{URL}/history", headers=owner.headers)).json()
    assert [p["id"] for p in own] == [str(i) for i in (owners_new, owners_old, owners_ended)]
    assert [p["mine"] for p in own] == [True, True, False]  # the co-owner's ended one too


async def test_history_holds_at_most_twelve(client, make_member):
    today = datetime.now(ICT).date()
    me = await make_member("owner")
    for k in range(14):
        start = today - timedelta(days=40 * (k + 1))
        await _plan(me.user_id, me.home_id, start, start + timedelta(days=29))
    got = (await client.get(f"{URL}/history", headers=me.headers)).json()
    assert len(got) == 12 and got[0]["start_on"] == (today - timedelta(days=40)).isoformat()


async def test_one_plan_is_read_by_its_person_or_from_an_owner(client, make_member):
    today = datetime.now(ICT).date()
    owner = await make_member("owner")
    me = await make_member("viewer", home_id=owner.home_id)
    other = await make_member("member", home_id=owner.home_id)
    owners = await _plan(owner.user_id, owner.home_id, today - timedelta(days=60), today)
    mine = await _plan(me.user_id, owner.home_id, today - timedelta(days=30), today)
    theirs = await _plan(other.user_id, owner.home_id, today - timedelta(days=20), today)
    stranger = await make_member("owner")

    got = await client.get(f"{URL}/{mine}", headers=me.headers)
    assert got.status_code == 200, got.text
    assert got.json()["mine"] is True and got.json()["days"][0]["actual"] == 10.5
    from_owner = await client.get(f"{URL}/{owners}", headers=me.headers)
    assert from_owner.status_code == 200 and from_owner.json()["mine"] is False
    # A housemate's own plan, another home's member, and an unknown id read as not found.
    assert (await client.get(f"{URL}/{theirs}", headers=me.headers)).status_code == 404
    assert (await client.get(f"{URL}/{mine}", headers=stranger.headers)).status_code == 404
    assert (await client.get(f"{URL}/{uuid.uuid4()}", headers=me.headers)).status_code == 404


def test_a_day_takes_the_mean_error_of_the_model_that_predicted_it():
    plan = SimpleNamespace(model_version="ctx-v2-a", bias=Decimal("0.48"))
    assert day_bias(plan, SimpleNamespace(version="ctx-v2-a", residuals=[9.0] * 20)) == 0.48
    # After a refit: the new model's own out-of-sample mean, none under 14 days of it.
    assert day_bias(plan, SimpleNamespace(version="ctx-v2-b", residuals=[2.0, 4.0] * 7)) == 3.0
    assert day_bias(plan, SimpleNamespace(version="ctx-v2-b", residuals=[2.0] * 13)) == 0.0


async def test_two_creates_at_once_answer_409_not_500(client, make_member, monkeypatch):
    today = datetime.now(ICT).date()
    _stub(monkeypatch, today)
    me = await make_member("viewer")
    device = await _device(me.home_id)
    body = {"start_on": today.isoformat(), "actions": [_action(device)]}
    assert (await client.post(URL, json=body, headers=me.headers)).status_code == 201

    async def none(*a):  # the second request read "no plan" before the first committed
        return None

    monkeypatch.setattr(plans_service, "current_plan", none)
    r = await client.post(URL, json=body, headers=me.headers)
    assert r.status_code == 409 and r.json()["code"] == "plan_exists", r.text


async def test_a_failing_freeze_still_creates_the_plan(client, make_member, monkeypatch):
    today = datetime.now(ICT).date()
    _stub(monkeypatch, today)
    me = await make_member("viewer")
    device = await _device(me.home_id)

    async def broken(*a, **kw):
        raise RuntimeError("model inputs missing")

    monkeypatch.setattr(plans_service, "freeze_plans", broken)
    body = {"start_on": today.isoformat(), "actions": [_action(device)]}
    r = await client.post(URL, json=body, headers=me.headers)
    assert r.status_code == 201, r.text  # the hourly job sets its days later
    assert (await client.get(f"{URL}/current", headers=me.headers)).status_code == 200


async def test_the_seed_keeps_the_demo_history_when_it_cannot_rebuild_it(make_member):
    from app.modules.insight.models import SavingsPlan
    from scripts.seed_demo_plans import replace_plans

    today = datetime.now(ICT).date()
    owner = await make_member("owner")
    old = await _plan(owner.user_id, owner.home_id, today - timedelta(days=60), today)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("UPDATE public.tb_savings_plan SET model_version = 'holdout-x' WHERE id = :i"),
            {"i": old},
        )
    async with SessionLocal() as s, s.begin():
        assert await replace_plans(s, owner.home_id, owner.user_id, []) is False
    async with SessionLocal() as s:
        assert await s.get(SavingsPlan, old) is not None  # nothing rebuilt: the old ones stay

    new = SavingsPlan(
        user_id=owner.user_id,
        home_id=owner.home_id,
        start_on=today - timedelta(days=30),
        end_on=today,
        model_version="holdout-y",
        sigma=None,
        bias=Decimal(0),
        forecast_kwh=Decimal(400),
        actions=[],
        days={},
        status="stopped",
    )
    async with SessionLocal() as s, s.begin():
        assert await replace_plans(s, owner.home_id, owner.user_id, [new]) is True
    async with SessionLocal() as s:
        versions = set(
            await s.scalars(
                select(SavingsPlan.model_version).where(SavingsPlan.home_id == owner.home_id)
            )
        )
    assert versions == {"holdout-y"}


async def test_a_freeze_failing_after_it_wrote_still_answers_201(client, make_member, monkeypatch):
    today = datetime.now(ICT).date()
    _stub(monkeypatch, today)
    me = await make_member("viewer")
    device = await _device(me.home_id)

    async def half(s, home_id, now):  # sets the new plan's days, then fails inside the savepoint
        plan = await plans_service.current_plan(s, me.user_id, home_id)
        plan.days = {today.isoformat(): {"expected": 1.0, "actual": 1.0}}
        await s.flush()
        raise RuntimeError("a later plan's inputs are missing")

    monkeypatch.setattr(plans_service, "freeze_plans", half)
    body = {"start_on": today.isoformat(), "actions": [_action(device)]}
    r = await client.post(URL, json=body, headers=me.headers)
    assert r.status_code == 201, r.text
    assert r.json()["days"] == []  # the failed freeze is rolled back; the job sets the days later


def test_the_seed_names_a_heater_action_with_its_own_numbers():
    from scripts.seed_demo_plans import LABELS

    assert LABELS["heater_setpoint"].format(name="x", degrees=2.0) == "Hạ nhiệt độ đặt 2°C"
    assert (
        LABELS["heater_earlier_off"].format(name="x", hours=1) == "Tắt sưởi sớm 1 giờ vào buổi tối"
    )
