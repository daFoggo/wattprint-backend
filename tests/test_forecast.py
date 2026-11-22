from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.modules.billing.services.forecast import project

ICT = timedelta(hours=7)


def at(d: date, hour: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=UTC) - ICT


def test_project_uses_the_weekday_mean_and_the_rest_of_today():
    # Two weeks: Mondays used 30 kWh, every other day 10.
    start = date(2026, 11, 2)  # a Monday
    history = {
        start + timedelta(days=i): Decimal(30 if (start + timedelta(days=i)).weekday() == 0 else 10)
        for i in range(14)
    }
    today = date(2026, 11, 16)  # a Monday, at 18:00: a quarter of it still ahead
    path = project(Decimal(100), at(today, 18), date(2026, 11, 18), history)
    assert [d for d, _ in path] == [today, date(2026, 11, 17), date(2026, 11, 18)]
    assert [float(c) for _, c in path] == [107.5, 117.5, 127.5]


def test_project_falls_back_to_the_overall_mean_for_a_missing_weekday():
    history = {date(2026, 11, 3): Decimal(20)}  # one Tuesday only
    path = project(Decimal(0), at(date(2026, 11, 8), 0), date(2026, 11, 8), history)  # a Sunday
    assert [float(c) for _, c in path] == [20.0]


def test_draws_center_on_p50_and_spread_with_residuals():
    import numpy as np

    from app.modules.billing.services.forecast import cycle_end_draws

    still = cycle_end_draws(100.0, [10.0, 10.0, 10.0], [])
    assert np.allclose(still, 130.0)
    draws = cycle_end_draws(100.0, [10.0] * 10, [-2.0, -1.0, 0.0, 1.0, 2.0], draws=4000)
    assert abs(np.median(draws) - 200.0) < 1.0
    assert np.percentile(draws, 90) > np.percentile(draws, 10) + 4
    assert np.array_equal(
        draws, cycle_end_draws(100.0, [10.0] * 10, [-2.0, -1.0, 0.0, 1.0, 2.0], draws=4000)
    )  # seeded: the same every call


def test_tier_probability_is_share_of_draws_over_the_tier():
    import numpy as np

    from app.modules.billing.services.forecast import cross_probability

    assert cross_probability(np.array([90.0, 110.0, 120.0, 95.0]), Decimal(100)) == 0.5
    assert cross_probability(np.array([90.0]), Decimal(100)) == 0.0


def test_change_splits_into_used_and_weather():
    from app.modules.billing.services.forecast import change_parts

    snapshot = {
        "version": "ctx-v1-a",
        "kwh_now": 100.0,
        "p50_daily": {"2026-11-20": 5.0, "2026-11-21": 10.0, "2026-11-22": 10.0},
        "groups_daily": {
            "2026-11-22": {"weather": 1.0, "calendar": 0.0, "occupancy": 0.0, "trend": 0.0}
        },
    }
    today = {
        "version": "ctx-v1-a",
        "kwh_now": 111.0,  # 6 kWh more than the 105 the snapshot expected by now...
        "p50_daily": {"2026-11-21": 5.0, "2026-11-22": 14.0},  # ...and today's rest as expected
        "groups_daily": {
            "2026-11-22": {"weather": 5.0, "calendar": 0.0, "occupancy": 0.0, "trend": 0.0}
        },
    }
    got = change_parts(snapshot, today, "2026-11-21", Decimal(3000), Decimal(30000))
    assert got["used"] == Decimal(3000)  # (111 + 5) - (100 + 5 + 10) = 1 kWh at 3.000 đ
    assert got["weather"] == Decimal(12000)  # 4 kWh more weather on the 22nd
    assert got["unexplained"] == Decimal(15000)  # what the tiers and rounding add
    assert sum(got.values()) == Decimal(30000)


def test_no_change_when_version_differs():
    from app.modules.billing.services.forecast import change_parts

    a = {"version": "ctx-v1-a", "kwh_now": 1.0, "p50_daily": {}, "groups_daily": {}}
    b = {**a, "version": "ctx-v1-b"}
    assert change_parts(a, b, "2026-11-21", Decimal(3000), Decimal(50000)) is None


def test_a_model_that_lost_its_backtest_does_not_forecast_the_bill():
    from types import SimpleNamespace

    from app.modules.billing.services.forecast import trusted

    def b(**bt):
        return SimpleNamespace(metrics={"backtest": bt} if bt else {})

    assert trusted(b(mape_v1=0.087, mape_ctx=0.076))
    assert not trusted(b(mape_v1=0.069, mape_ctx=0.079))
    assert trusted(b())  # not tried yet: the model's own range is shown


def test_the_accuracy_shown_is_the_shown_methods_own():
    from types import SimpleNamespace

    from app.modules.billing.services.forecast import backtest_accuracy

    b = SimpleNamespace(metrics={"backtest": {"mape_v1": 0.091, "mape_ctx": 0.163, "cycles": 6}})
    assert backtest_accuracy(b, "weekday").error_pct == 0.091
    assert backtest_accuracy(b, "context").error_pct == 0.163
    assert backtest_accuracy(SimpleNamespace(metrics={}), "context") is None
    assert backtest_accuracy(None, "weekday") is None


async def test_a_snapshot_of_another_cycle_explains_nothing(make_member):
    from datetime import date as d

    from sqlalchemy import text

    from app.database import SessionLocal
    from app.modules.billing.services.forecast import _snapshot_before

    me = await make_member("owner")
    async with SessionLocal() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO public.tb_forecast_snapshot (home_id, generated_at, horizon_date, "
                "kwh, amount, model_version, drivers) VALUES (:h, :g, :d, 200, 600000, 'v', '{}')"
            ),
            {"h": me.home_id, "g": datetime(2026, 11, 30, 3, tzinfo=UTC), "d": d(2026, 11, 30)},
        )
    async with SessionLocal() as s:
        assert await _snapshot_before(s, me.home_id, d(2026, 12, 1), d(2026, 12, 31)) is None
        assert await _snapshot_before(s, me.home_id, d(2026, 12, 1), d(2026, 11, 30)) is not None
