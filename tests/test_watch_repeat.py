from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.modules.insight.models import Alert, Watch
from app.modules.insight.services import watches as svc
from app.modules.insight.services.watches import run_alerts

T0 = datetime(2026, 11, 21, 3, 0, tzinfo=UTC)  # 10:00 in Hanoi


def minutes(start: datetime, n: int, watts: float = 500.0, peak: float | None = None):
    """n on-minutes of a device from `start`: (bucket, avg_w, energy_wh, max_w)."""
    return [
        (start + timedelta(minutes=i), watts, watts / 60, peak if peak else watts) for i in range(n)
    ]


def test_device_on_alerts_each_new_run_only():
    created = T0
    old = minutes(T0 - timedelta(minutes=5), 10)  # was already running when the watch was set
    new = minutes(T0 + timedelta(minutes=30), 10)
    now = T0 + timedelta(minutes=60)
    got = run_alerts("device_on", 0, old + new, 100, created, now)
    assert [k for k, _ in got] == [new[0][0]]


def test_device_off_waits_for_the_run_to_end():
    run = minutes(T0 + timedelta(minutes=1), 10)
    assert run_alerts("device_off", 0, run, 100, T0, run[-1][0] + timedelta(minutes=1)) == []
    ended = run_alerts("device_off", 0, run, 100, T0, run[-1][0] + timedelta(minutes=10))
    assert [k for k, _ in ended] == [run[0][0]]


def test_long_run_alerts_while_running_once():
    run = minutes(T0 + timedelta(minutes=1), 100)
    now = run[-1][0] + timedelta(minutes=1)  # still going, 100 minutes in
    assert run_alerts("device_run_min", 90, run, 100, T0, now) == [(run[0][0], 100.0)]
    assert run_alerts("device_run_min", 120, run, 100, T0, now) == []


def test_high_power_run_alerts_once():
    run = minutes(T0 + timedelta(minutes=1), 10, watts=800, peak=2500)
    got = run_alerts("device_power_w", 2000, run, 100, T0, T0 + timedelta(hours=1))
    assert got == [(run[0][0], 2500.0)]
    assert run_alerts("device_power_w", 3000, run, 100, T0, T0 + timedelta(hours=1)) == []


def test_the_same_run_gives_the_same_key_on_every_check():
    run = minutes(T0 + timedelta(minutes=1), 10)
    first = run_alerts("device_on", 0, run, 100, T0, T0 + timedelta(minutes=20))
    later = run_alerts("device_on", 0, run, 100, T0, T0 + timedelta(minutes=40))
    assert first == later


async def test_repeating_daily_watch_fires_once_a_day(make_member, monkeypatch):
    async def twelve(*_a, **_k):
        return Decimal(12)

    monkeypatch.setattr(svc, "measure", twelve)
    me = await make_member("owner")
    async with SessionLocal() as s, s.begin():
        w, _ = await svc.create_watch(
            s,
            me.user_id,
            me.home_id,
            metric="today_kwh",
            op="gt",
            threshold=10,
            label="Điện năng hôm nay",
            now=T0,
            repeat=True,
        )
        wid = w.id
    for now in (T0 + timedelta(minutes=10), T0 + timedelta(hours=5)):
        async with SessionLocal() as s, s.begin():
            await svc._check(s, await s.get(Watch, wid), now)
    async with SessionLocal() as s:
        w = await s.get(Watch, wid)
        hits = list(await s.scalars(select(Alert).where(Alert.dedup_key.like(f"watch:{wid}%"))))
    assert (w.status, len(hits)) == ("active", 1)
    # it sleeps until local midnight, then judges the next day again
    assert w.next_check_at == datetime(2026, 11, 21, 17, 0, tzinfo=UTC)
    async with SessionLocal() as s, s.begin():
        await svc._check(s, await s.get(Watch, wid), T0 + timedelta(days=1))
    async with SessionLocal() as s:
        hits = list(await s.scalars(select(Alert).where(Alert.dedup_key.like(f"watch:{wid}%"))))
    assert len(hits) == 2


@pytest.mark.parametrize("repeat, days", [(True, 365), (False, 30)])
async def test_default_end(make_member, monkeypatch, repeat, days):
    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(svc, "measure", nothing)
    me = await make_member("owner")
    async with SessionLocal() as s, s.begin():
        w, _ = await svc.create_watch(
            s,
            me.user_id,
            me.home_id,
            metric="power_w",
            op="gt",
            threshold=9000,
            label="Công suất",
            now=T0,
            repeat=repeat,
        )
    assert w.ends_at == T0 + timedelta(days=days)


def _alert_row(kind, **payload):
    return Alert(kind=kind, payload={"watch_id": "w", "label": "Máy giặt", **payload})


def test_mail_text_for_device_runs_and_repeats():
    from app.modules.insight.services.mail import alert_text

    on = alert_text(
        _alert_row("device_on", device="Máy giặt", at="2026-11-21T03:30:00+00:00"), None
    )
    assert "Máy giặt" in on[0] and "bật" in on[0]
    long = alert_text(
        _alert_row("device_long_run", device="Máy giặt", value=95.0, threshold=90), None
    )
    assert "95" in long[1] and "90" in long[0]
    again = alert_text(
        _alert_row("watch_hit", op="gt", threshold=10, unit="kwh", value=12, repeat=True), None
    )
    assert "đã tắt" not in again[1]


def test_a_rewritten_first_minute_is_the_same_run():
    run = minutes(T0 + timedelta(minutes=30), 10)
    earlier = minutes(T0 + timedelta(minutes=29), 11)  # NILM lifted the minute before over on_w
    now = T0 + timedelta(minutes=60)
    told = run_alerts("device_on", 0, run, 100, T0, now)
    assert run_alerts("device_on", 0, earlier, 100, T0, now, last_at=told[0][0]) == []
    later = minutes(T0 + timedelta(minutes=31), 9)
    assert run_alerts("device_on", 0, later, 100, T0, now, last_at=told[0][0]) == []
    next_run = minutes(T0 + timedelta(minutes=90), 5)
    got = run_alerts(
        "device_on", 0, run + next_run, 100, T0, now + timedelta(hours=1), last_at=told[0][0]
    )
    assert [k for k, _ in got] == [next_run[0][0]]


def test_a_run_cut_by_the_window_edge_is_not_new():
    always = minutes(T0, 120)  # on before the window began (an always-on load)
    later = T0 + timedelta(minutes=121)
    # the watch is older than the window: the run's first minute is only where reading began
    assert (
        run_alerts("device_on", 0, always, 100, T0 - timedelta(hours=1), later, window_start=T0)
        == []
    )


async def test_device_run_alerts_refuse_the_unknown_load(make_member):
    from app.modules.insight.utils import WatchError
    from tests.test_watches import _device

    me = await make_member("owner")
    other = await _device(me.home_id, name="Khác")
    async with SessionLocal() as s:
        await s.execute(
            __import__("sqlalchemy").text(
                "UPDATE public.tb_device SET device_type_code = 'other' WHERE id = :d"
            ),
            {"d": other},
        )
        await s.commit()
    with pytest.raises(WatchError) as e:
        async with SessionLocal() as s, s.begin():
            await svc.create_watch(
                s,
                me.user_id,
                me.home_id,
                metric="device_on",
                op="gt",
                threshold=0,
                label="Khác bật",
                now=T0,
                device_id=other,
            )
    assert e.value.code == "bad_device"


def test_the_window_edge_holds_off_the_minute():
    always = minutes(T0 + timedelta(minutes=1), 120)  # first bucket read: the minute after `since`
    since = T0 + timedelta(
        seconds=15
    )  # analyzed_until has seconds; the query starts a bucket later
    later = T0 + timedelta(minutes=122)
    assert (
        run_alerts("device_on", 0, always, 100, T0 - timedelta(hours=1), later, window_start=since)
        == []
    )


def test_mail_repeat_text_follows_the_direction():
    from app.modules.insight.services.mail import alert_text

    below = alert_text(
        _alert_row("watch_hit", op="lt", threshold=500000, unit="vnd", value=400000, repeat=True),
        None,
    )
    assert "vượt" not in below[1] and "dưới" in below[1]
