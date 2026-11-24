import pytest

from app.modules.insight.services.device_signals import (
    Run,
    daily_excess,
    denser_cycling,
    long_run,
    odd_hour,
    peers_of,
)


def run(minutes: float, kwh: float, hour: int = 10, temp: float = 20.0, day: int = 0) -> Run:
    return Run(minutes=minutes, kwh=kwh, start_hour=hour, temp_c=temp, day=day)


def test_daily_excess_fires_over_the_band_and_money():
    got = daily_excess(2.1, 1.3, 1.6, 3000.0, 1.0)
    assert got["signal"] == "daily" and got["excess_kwh"] == pytest.approx(0.8)
    assert got["excess_vnd"] == 2400 and got["usual"] == 1.3
    assert daily_excess(1.5, 1.3, 1.6, 3000.0, 1.0) is None  # inside the band
    assert daily_excess(2.0, 1.9, 1.95, 3000.0, 1.0) is None  # under 2.000 đ


def test_long_run_against_peers_in_the_same_block_and_temperature():
    history = [run(100, 1.0, hour=10, temp=20 + (i % 3)) for i in range(10)]
    history += [run(300, 3.0, hour=2, temp=20) for _ in range(5)]  # another block: not peers
    history += [run(300, 3.0, hour=10, temp=5) for _ in range(5)]  # colder: not peers
    new = run(190, 1.9, hour=11, temp=21)
    peers = peers_of(new, history)
    assert len(peers) == 10
    got = long_run(new, peers, 3000.0, 1.0)
    assert got["signal"] == "long_run" and got["value"] == 190 and got["usual"] == 100
    assert got["excess_vnd"] == pytest.approx(2700)
    assert long_run(run(140, 1.4, hour=11, temp=21), peers, 3000.0, 1.0) is None  # < 1.5×
    assert long_run(new, peers[:5], 3000.0, 1.0) is None  # too few peers


def test_odd_hour_needs_history_and_rarity():
    got = odd_hour(start_hour=3, days_at_hour=1, days=60, runs=40)
    assert got["signal"] == "odd_hour" and got["value"] == 3
    assert odd_hour(start_hour=3, days_at_hour=3, days=60, runs=40) is None  # 5 % of days
    assert odd_hour(start_hour=3, days_at_hour=0, days=20, runs=40) is None  # under 28 days
    assert odd_hour(start_hour=3, days_at_hour=0, days=60, runs=10) is None  # under 20 runs
    assert odd_hour(start_hour=3, days_at_hour=1, days=60, runs=40, factor=2.0) is None


def test_denser_cycling_for_three_days():
    got = denser_cycling([0.50, 0.52, 0.51], 0.40, 3.0, 3000.0)
    assert got["signal"] == "denser" and got["value"] == pytest.approx(0.51)
    assert got["excess_vnd"] == pytest.approx((0.51 / 0.40 - 1) * 3.0 * 3000.0, rel=0.01)
    assert denser_cycling([0.50, 0.41, 0.51], 0.40, 2.4, 3000.0) is None  # one day back to usual
    assert denser_cycling([0.50, 0.52], 0.40, 2.4, 3000.0) is None  # under 3 days
