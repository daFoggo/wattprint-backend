from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.database import SessionLocal
from app.modules.insight.models import Alert
from app.modules.insight.services import detectors
from app.modules.insight.services.detectors import Finding, settle_devices

UNTIL = datetime(2026, 11, 23, 6, 0, tzinfo=UTC)  # 13:00 in Hanoi


@pytest.fixture
async def device(monkeypatch):
    async def price(*a, **k):
        return 3000.0

    monkeypatch.setattr(detectors, "_avg_price", price)
    async with SessionLocal() as s, s.begin():
        hid = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('dev') RETURNING id"))
        did = await s.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'washing_machine', 'Washing Machine', 'nilm') RETURNING id"
            ),
            {"h": hid},
        )
    yield hid, did
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})


async def runs(hid, did, starts_minutes_kwh):
    async with SessionLocal() as s, s.begin():
        for start, minutes, kwh in starts_minutes_kwh:
            await s.execute(
                text(
                    "INSERT INTO public.tb_device_cycle (home_id, device_id, start_ts, end_ts, "
                    "energy_wh, peak_w) VALUES (:h, :d, :a, :b, :e, 2000)"
                ),
                {
                    "h": hid,
                    "d": did,
                    "a": start,
                    "b": start + timedelta(minutes=minutes),
                    "e": kwh * 1000,
                },
            )


def history(n: int = 30):
    # 10:00 local (03:00 UTC) every day for n days, 100 minutes, 1 kWh
    return [(UNTIL - timedelta(days=d, hours=3), 100, 1.0) for d in range(1, n + 1)]


async def test_a_long_run_is_an_alert(device):
    hid, did = device
    await runs(hid, did, [*history(), (UNTIL - timedelta(hours=4), 200, 2.0)])
    async with SessionLocal() as s:
        found = await detectors._device_anomalies(s, hid, UNTIL, UNTIL)
    assert [f.payload["signal"] for f in found] == ["long_run"]
    assert found[0].device_id == did
    assert found[0].dedup_key == f"device_anomaly:{did}:2026-11-23"


async def test_unanalysed_minutes_are_not_judged(device):
    hid, did = device
    # the long run ends after NILM's analysed time: not judged yet
    await runs(hid, did, [*history(), (UNTIL - timedelta(minutes=150), 200, 2.0)])
    async with SessionLocal() as s:
        assert await detectors._device_anomalies(s, hid, UNTIL, UNTIL) == []


async def test_silent_without_history(device):
    hid, did = device
    await runs(hid, did, [*history(5), (UNTIL - timedelta(hours=4), 200, 2.0)])
    async with SessionLocal() as s:
        assert await detectors._device_anomalies(s, hid, UNTIL, UNTIL) == []


async def test_one_alert_per_device_per_day(device):
    hid, did = device
    f = Finding(
        "device_anomaly",
        f"device_anomaly:{did}:2026-11-23",
        "warning",
        {"signal": "long_run", "excess_vnd": 2700.0},
        did,
    )
    g = Finding(
        "device_anomaly", f"device_anomaly:{did}:2026-11-23", "warning", {"signal": "odd_hour"}, did
    )
    async with SessionLocal() as s, s.begin():
        await settle_devices(s, hid, [f], UNTIL)
    async with SessionLocal() as s, s.begin():
        await settle_devices(s, hid, [g], UNTIL + timedelta(hours=1))
        await settle_devices(s, hid, [], UNTIL + timedelta(hours=2))
    async with SessionLocal() as s:
        rows = (await s.scalars(select(Alert).where(Alert.home_id == hid))).all()
    assert len(rows) == 1 and rows[0].status == "open"
    async with SessionLocal() as s, s.begin():
        await settle_devices(s, hid, [], UNTIL + timedelta(days=1))
    async with SessionLocal() as s:
        rows = (await s.scalars(select(Alert).where(Alert.home_id == hid))).all()
    assert [r.status for r in rows] == ["resolved"]


async def test_feedback_widens_one_device_only(device, make_member):
    from app.modules.insight.services.feedback import record_feedback, sensitivity

    hid, did = device
    member = await make_member("owner", home_id=hid)
    async with SessionLocal() as s, s.begin():
        other = await s.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'kettle', 'Kettle', 'nilm') RETURNING id"
            ),
            {"h": hid},
        )
        aid = await s.scalar(
            text(
                "INSERT INTO public.tb_alert (home_id, device_id, kind, severity, ts, payload, "
                "dedup_key) VALUES (:h, :d, 'device_anomaly', 'warning', now(), "
                "'{\"signal\": \"long_run\"}', 'x') RETURNING id"
            ),
            {"h": hid, "d": did},
        )
        assert await record_feedback(s, hid, member.user_id, aid, "not_anomaly")
        assert await sensitivity(s, hid, "device_anomaly", did, "long_run") == 1.5
        assert await sensitivity(s, hid, "device_anomaly", did, "odd_hour") == 1.0
        assert await sensitivity(s, hid, "device_anomaly", other, "long_run") == 1.0


def test_device_anomaly_mail_names_the_device_and_the_usual():
    from types import SimpleNamespace

    from app.modules.insight.services.mail import alert_text

    a = SimpleNamespace(
        kind="device_anomaly",
        payload={
            "signal": "long_run",
            "value": 190,
            "usual": 100,
            "unit": "min",
            "excess_kwh": 0.9,
            "excess_vnd": 2700.0,
            "at": "2026-11-23T03:00:00+00:00",
        },
    )
    subject, body = alert_text(a, "Washing Machine")
    assert "Washing Machine" in subject and "190" in body and "100" in body
    for signal in ("daily", "odd_hour", "denser"):
        alert_text(
            SimpleNamespace(
                kind="device_anomaly",
                payload={**a.payload, "signal": signal, "value": 3, "usual": 1.2},
            ),
            "Fridge-Freezer",
        )


async def test_a_run_is_judged_once_on_the_day_it_ended(device):
    hid, did = device
    ended = UNTIL - timedelta(hours=4)  # 09:00 local on the 23rd
    await runs(hid, did, [*history(), (ended - timedelta(minutes=200), 200, 2.0)])
    async with SessionLocal() as s:
        assert len(await detectors._device_anomalies(s, hid, UNTIL, UNTIL)) == 1
        next_day = UNTIL + timedelta(hours=14)  # 03:00 local on the 24th, the run still in 24 h
        assert await detectors._device_anomalies(s, hid, next_day, next_day) == []


async def test_alerts_settle_on_the_analysed_day_not_the_clock(device):
    hid, did = device
    late = datetime(2026, 11, 23, 16, 50, tzinfo=UTC)  # 23:50 local: what NILM has analysed
    f = Finding(
        "device_anomaly", f"device_anomaly:{did}:2026-11-23", "warning", {"signal": "odd_hour"}, did
    )
    async with SessionLocal() as s, s.begin():
        await settle_devices(s, hid, [f], late, now=late + timedelta(minutes=20))  # 00:10 local
    async with SessionLocal() as s:
        rows = (await s.scalars(select(Alert).where(Alert.home_id == hid))).all()
    assert [r.status for r in rows] == ["open"]


async def test_d2_waits_for_28_days_and_20_runs(device):
    hid, did = device
    # 10 days, 10 peers: enough peers, not enough history
    await runs(hid, did, [*history(10), (UNTIL - timedelta(hours=4), 200, 2.0)])
    async with SessionLocal() as s:
        assert await detectors._device_anomalies(s, hid, UNTIL, UNTIL) == []


def test_d4_compares_with_days_at_the_same_temperature():
    from app.modules.insight.services.detectors import same_temperature

    # old days 30..33 days back at 10 °C and 34..37 at 25 °C; the last 3 days at 24 °C
    old = {100 - k: (0.4 if k < 34 else 0.3, 10.0 if k < 34 else 25.0) for k in range(30, 38)}
    assert same_temperature(old, 24.0) == pytest.approx(0.3)
    assert same_temperature(old, 17.0) is None  # no old day within ±3 °C


async def test_d1_judges_whole_hours_up_to_the_analysed_minute(device, monkeypatch):
    import pandas as pd

    hid, did = device
    until = UNTIL + timedelta(minutes=30)  # NILM's window ended mid-hour
    hours = pd.date_range(datetime(2026, 11, 22, 17, tzinfo=UTC), UNTIL, freq="h", inclusive="left")
    seen = {}

    async def band(s, h, d, lo, hi, now):
        seen["hi"] = hi
        idx = pd.date_range(lo, hi, freq="h", inclusive="left")
        return pd.DataFrame({"p50": 0.05, "p95": 0.08}, index=idx)

    async def actual(s, d, lo, hi):
        return pd.Series(0.2, index=pd.date_range(lo, hi, freq="h", inclusive="left"))

    monkeypatch.setattr(detectors, "device_band", band)
    monkeypatch.setattr(detectors, "device_actual", actual)
    await runs(hid, did, history())
    async with SessionLocal() as s:
        found = await detectors._device_anomalies(s, hid, until, until)
    assert seen["hi"] == UNTIL and len(hours) == 13
    assert [f.payload["signal"] for f in found] == ["daily"]


async def test_a_failing_device_model_does_not_undo_the_home(device, monkeypatch):
    from app.modules.insight.services import jobs

    hid, did = device
    async with SessionLocal() as s, s.begin():
        other = await s.scalar(
            text(
                "INSERT INTO public.tb_device (home_id, device_type_code, name, origin) "
                "VALUES (:h, 'kettle', 'Kettle', 'nilm') RETURNING id"
            ),
            {"h": hid},
        )
        for d in (did, other):
            await s.execute(
                text(
                    "INSERT INTO public.tb_series (home_id, kind, device_id, metric, unit) "
                    "VALUES (:h, 'device', :d, 'power_w', 'W')"
                ),
                {"h": hid, "d": d},
            )
    tried = []

    async def train(s, home_id, device_id, now):
        tried.append(device_id)
        await s.execute(text("SELECT 1"))  # the session still works inside the savepoint
        if device_id == did:
            raise ValueError("empty dataset")
        return "v"

    monkeypatch.setattr(jobs, "train_device", train)
    async with SessionLocal() as s, s.begin():
        await jobs.train_devices(s, hid, UNTIL)  # the first fails, logs, the second still trains
        assert await s.scalar(text("SELECT 1")) == 1  # the home's transaction is still usable
    assert set(tried) == {did, other}
