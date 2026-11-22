from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.modules.energy.api import weather_inputs

NOW = datetime(2026, 11, 21, 3, 0, tzinfo=UTC)
YEAR = timedelta(days=364)


@pytest.fixture
async def home():
    async with SessionLocal() as s, s.begin():
        home_id = await s.scalar(
            text("INSERT INTO public.tb_home (name) VALUES ('weather test') RETURNING id")
        )
    yield home_id
    async with SessionLocal() as s, s.begin():
        await s.execute(text("DELETE FROM public.tb_home WHERE id = :h"), {"h": home_id})


async def put(home_id, rows: dict[datetime, float]) -> None:
    async with SessionLocal() as s, s.begin():
        for ts, temp in rows.items():
            await s.execute(
                text(
                    "INSERT INTO public.tb_home_weather_hourly (home_id, ts, temp_c, humidity_pct, "
                    "apparent_c, cloud_pct, radiation_wm2, precip_mm, is_day) "
                    "VALUES (:h, :t, :c, 80, :c, 50, 0, 0, false)"
                ),
                {"h": home_id, "t": ts, "c": temp},
            )


async def test_observed_up_to_five_days_then_the_normal(home):
    far, near = NOW + timedelta(days=6), NOW + timedelta(days=4)
    rows = {far: 30.0, near: 30.0}
    for d in range(-7, 8):  # the same hour within ±7 days, one 52-week year earlier
        rows[far - YEAR + timedelta(days=d)] = 10.0
    await put(home, rows)
    async with SessionLocal() as s:
        w = await weather_inputs(s, home, far, far + timedelta(hours=1), NOW)
        assert w.loc[far, "temp_c"] == pytest.approx(10.0)
        w = await weather_inputs(s, home, near, near + timedelta(hours=1), NOW)
        assert w.loc[near, "temp_c"] == pytest.approx(30.0)


async def test_cold_spell_lowers_temperature_in_its_window_only(home):
    inside, outside = NOW + timedelta(hours=1), NOW + timedelta(hours=5)
    await put(home, {inside: 10.0, outside: 10.0})
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_demo_scenario (home_id, name, starts_at, ends_at, params, "
                "train) VALUES (:h, 'cold_spell', :a, :b, '{\"delta_c\": 8}', false)"
            ),
            {"h": home, "a": NOW, "b": NOW + timedelta(hours=3)},
        )
    async with SessionLocal() as s:
        w = await weather_inputs(s, home, NOW, NOW + timedelta(hours=6), NOW)
    assert w.loc[inside, "temp_c"] == pytest.approx(2.0)
    assert w.loc[inside, "apparent_c"] == pytest.approx(2.0)
    assert w.loc[outside, "temp_c"] == pytest.approx(10.0)


async def test_missing_hours_are_nan_not_dropped(home):
    await put(home, {NOW: 12.0})
    async with SessionLocal() as s:
        w = await weather_inputs(s, home, NOW, NOW + timedelta(hours=4), NOW)
    assert len(w) == 4
    assert w["temp_c"].isna().sum() == 3
