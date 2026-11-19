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
