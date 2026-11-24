from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.database import SessionLocal

H0 = datetime(2026, 11, 21, 0, tzinfo=UTC)


async def put_expected(home_id, n: int = 3, p50: float = 1.0) -> None:
    async with SessionLocal() as s, s.begin():
        for i in range(n):
            await s.execute(
                text(
                    "INSERT INTO public.tb_expect_hourly (home_id, ts, p05, p10, p50, p90, p95, "
                    "c_weather, c_calendar, c_occupancy, c_trend, c_base, model_version) "
                    "VALUES (:h, :t, 0.5, 0.6, :m, 1.4, 1.6, 0.1, 0.2, 0.3, 0.0, 0.4, 'ctx-v1-t')"
                ),
                {"h": home_id, "t": H0 + timedelta(hours=i), "m": p50},
            )


async def test_expected_needs_a_token(client):
    r = await client.get(f"/api/v1/expected?from={H0.isoformat()}&to={H0.isoformat()}")
    assert r.status_code == 401


async def test_expected_returns_hours_for_the_members_home(client, make_member):
    me, other = await make_member("owner"), await make_member("owner")
    await put_expected(me.home_id, 3, 1.0)
    await put_expected(other.home_id, 3, 9.0)
    r = await client.get(
        "/api/v1/expected",
        params={"from": H0.isoformat(), "to": (H0 + timedelta(hours=2)).isoformat()},
        headers=me.headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [h["p50"] for h in body] == [1.0, 1.0]  # [from, to): two hours, none of the other home
    assert body[0]["p10"] == pytest.approx(0.6) and body[0]["p90"] == pytest.approx(1.4)
    assert body[0]["kwh"] is None
    assert body[0]["model_version"] == "ctx-v1-t"  # which model, so a client can tell a refit


async def test_expected_is_empty_without_a_model(client, make_member):
    me = await make_member("owner")
    r = await client.get(
        "/api/v1/expected",
        params={"from": H0.isoformat(), "to": (H0 + timedelta(hours=5)).isoformat()},
        headers=me.headers,
    )
    assert r.status_code == 200 and r.json() == []


async def test_expected_rejects_more_than_8_days(client, make_member):
    me = await make_member("owner")
    r = await client.get(
        "/api/v1/expected",
        params={"from": H0.isoformat(), "to": (H0 + timedelta(days=9)).isoformat()},
        headers=me.headers,
    )
    assert r.status_code == 422
