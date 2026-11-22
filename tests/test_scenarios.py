from datetime import UTC, datetime, timedelta

import pytest

from app.modules.ops.api import DemoScenario, ReadingRow
from scripts.backfill_nilm import backfill_windows
from scripts.scenarios import apply, heater_w

T0 = datetime(2026, 11, 21, 11, 0, tzinfo=UTC)  # 18:00 in Hanoi


def row(ts: datetime, watts: float = 300.0, quality: int = 0) -> ReadingRow:
    return ReadingRow(ts, "Aggregate", watts, quality)


def sc(name: str, start: datetime, end: datetime | None = None, **params) -> DemoScenario:
    return DemoScenario(name=name, starts_at=start, ends_at=end, params=params, train=False)


def test_heater_follows_cold_inside_its_hours():
    assert heater_w(16.0, 18, {}) == 0
    assert heater_w(6.0, 18, {}) == pytest.approx(1800)
    assert heater_w(6.0, 13, {}) == 0
    assert heater_w(-20.0, 7, {}) == 2000
    assert heater_w(10.0, 18, {"w_per_c": 100, "setpoint_c": 20}) == pytest.approx(1000)


def test_apply_adds_heater_from_the_hour_temperature():
    rows = [row(T0), row(T0 + timedelta(hours=8))]  # 18:00 and 02:00 in Hanoi
    out = apply(rows, [sc("heater", T0 - timedelta(days=1))], lambda ts: 6.0)
    assert [r.value for r in out] == [pytest.approx(2100), 300]


def test_apply_adds_forgotten_load_only_in_window():
    rows = [row(T0 - timedelta(minutes=1)), row(T0), row(T0 + timedelta(hours=6))]
    scen = [sc("forgotten_load", T0, T0 + timedelta(hours=6), watts=800)]
    assert [r.value for r in apply(rows, scen, lambda ts: 10.0)] == [300, 1100, 300]


def test_base_up_runs_on_without_an_end():
    out = apply([row(T0 + timedelta(days=30))], [sc("base_up", T0)], lambda ts: 10.0)
    assert out[0].value == 360  # default 60 W


def test_away_caps_at_base():
    rows = [row(T0, 1500), row(T0 + timedelta(minutes=1), 80)]
    out = apply(rows, [sc("away", T0, T0 + timedelta(days=3), base_w=120)], lambda ts: 10.0)
    assert [r.value for r in out] == [120, 80]


def test_apply_keeps_quality_and_timestamps():
    rows = [row(T0, quality=1)]
    out = apply(rows, [sc("forgotten_load", T0, T0 + timedelta(hours=1))], lambda ts: 10.0)
    assert (out[0].ts, out[0].quality, out[0].channel) == (T0, 1, "Aggregate")


def test_cold_spell_changes_no_reading_itself():
    rows = [row(T0)]
    assert (
        apply(rows, [sc("cold_spell", T0, T0 + timedelta(hours=2), delta_c=8)], lambda ts: 10.0)[
            0
        ].value
        == 300
    )


def test_backfill_window_stops_before_first_estimate():
    lo = datetime(2026, 1, 1, tzinfo=UTC)
    first = datetime(2026, 1, 3, 12, tzinfo=UTC)
    assert backfill_windows(lo, first, timedelta(days=1)) == [
        (lo, lo + timedelta(days=1)),
        (lo + timedelta(days=1), lo + timedelta(days=2)),
        (lo + timedelta(days=2), first),
    ]
    assert backfill_windows(first, first, timedelta(days=1)) == []
