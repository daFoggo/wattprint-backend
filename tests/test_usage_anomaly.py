import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.database import SessionLocal
from app.modules.insight.models import Alert
from app.modules.insight.services.detectors import Finding, judge, rule_kinds, settle_usage
from app.modules.insight.services.feedback import record_feedback, sensitivity

NOW = datetime(2026, 11, 21, 8, 30, tzinfo=UTC)  # 15:30 in Hanoi


def test_fires_when_actual_exceeds_band_and_money():
    got = judge([2.0, 2.0, 2.0], [1.0] * 3, [1.3] * 3, 3000.0, 2000.0, 1.0)
    assert got == {"excess_kwh": 3.0, "excess_vnd": 9000.0, "expected_kwh": 3.0, "actual_kwh": 6.0}


def test_silent_under_money_threshold():
    assert judge([1.4] * 3, [1.0] * 3, [1.3] * 3, 1000.0, 2000.0, 1.0) is None


def test_silent_over_a_gap_hour():
    assert judge([2.0, math.nan, 2.0], [1.0] * 3, [1.3] * 3, 3000.0, 2000.0, 1.0) is None


def test_feedback_widens_band():
    actual, p50, p95 = [1.4] * 3, [1.0] * 3, [1.3] * 3
    assert judge(actual, p50, p95, 3000.0, 2000.0, 1.0) is not None  # 4.2 kWh over a 3.9 bar
    assert judge(actual, p50, p95, 3000.0, 2000.0, 1.5) is None  # the bar is now 4.35


def test_old_rule_skipped_with_model():
    assert "unexplained_load" not in rule_kinds(True) and "usage_anomaly" in rule_kinds(True)


def test_no_model_keeps_the_old_rule_and_no_usage_anomaly():
    assert "unexplained_load" in rule_kinds(False) and "usage_anomaly" not in rule_kinds(False)


@pytest.fixture
async def home():
    async with SessionLocal() as s, s.begin():
        hid = await s.scalar(text("INSERT INTO public.tb_home (name) VALUES ('a1') RETURNING id"))
    yield hid
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": hid})


def finding(day: str, excess: float) -> Finding:
    return Finding("usage_anomaly", f"usage_anomaly:{day}", "warning", {"excess_kwh": excess})


async def test_one_per_day_after_acknowledge(home):
    async with SessionLocal() as s, s.begin():
        await settle_usage(s, home, [finding("2026-11-21", 2.0)], NOW)
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text("UPDATE public.tb_alert SET status = 'acknowledged' WHERE home_id = :h"),
            {"h": home},
        )
        await settle_usage(s, home, [finding("2026-11-21", 3.0)], NOW + timedelta(hours=1))
        await settle_usage(s, home, [], NOW + timedelta(hours=2))  # gone again: still today's
    async with SessionLocal() as s:
        rows = (await s.scalars(select(Alert).where(Alert.home_id == home))).all()
    assert len(rows) == 1 and rows[0].payload["excess_kwh"] == 3.0
    assert rows[0].status == "acknowledged"
    async with SessionLocal() as s, s.begin():  # the next local day
        await settle_usage(s, home, [finding("2026-11-22", 1.0)], NOW + timedelta(days=1))
    async with SessionLocal() as s:
        rows = (
            await s.scalars(select(Alert).where(Alert.home_id == home).order_by(Alert.ts))
        ).all()
    assert [r.status for r in rows] == ["resolved", "open"]


async def test_feedback_raises_the_homes_sensitivity_factor(home, make_member):
    member = await make_member("owner", home_id=home)
    async with SessionLocal() as s, s.begin():
        aid = await s.scalar(
            text(
                "INSERT INTO public.tb_alert (home_id, kind, severity, ts, payload, dedup_key) "
                "VALUES (:h, 'usage_anomaly', 'warning', now(), '{}', 'usage_anomaly:x') "
                "RETURNING id"
            ),
            {"h": home},
        )
        assert await sensitivity(s, home, "usage_anomaly") == 1.0
        assert await record_feedback(s, home, member.user_id, aid, "not_anomaly")
        assert await sensitivity(s, home, "usage_anomaly") == 1.5
        assert not await record_feedback(s, uuid.uuid4(), member.user_id, aid, "useful")


async def test_feedback_on_other_homes_alert_is_404(client, make_member):
    me, other = await make_member("owner"), await make_member("owner")
    async with SessionLocal() as s, s.begin():
        aid = await s.scalar(
            text(
                "INSERT INTO public.tb_alert (home_id, kind, severity, ts, payload, dedup_key) "
                "VALUES (:h, 'usage_anomaly', 'warning', now(), '{}', 'usage_anomaly:y') "
                "RETURNING id"
            ),
            {"h": other.home_id},
        )
    r = await client.post(
        f"/api/v1/insights/alerts/{aid}/feedback",
        json={"verdict": "not_anomaly"},
        headers=me.headers,
    )
    assert r.status_code == 404 and r.json()["code"] == "alert_not_found"
    ok = await client.post(
        f"/api/v1/insights/alerts/{aid}/feedback",
        json={"verdict": "useful"},
        headers=other.headers,
    )
    assert ok.status_code == 204
    listed = await client.get("/api/v1/insights/alerts", headers=other.headers)
    assert listed.json()[0]["feedback"] == "useful"
