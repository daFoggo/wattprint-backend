import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

_path = next(
    (Path(__file__).resolve().parents[1] / "alembic/versions/updates").glob("*_5d0c9a3e7f21_*.py")
)
_spec = importlib.util.spec_from_file_location("refresh_refit", _path)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

DAY = timedelta(days=1)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_windows_cover_whole_local_days_and_stop_before_today():
    now = utc(2026, 11, 12, 5)  # 12:00 local, so today's bucket opened at 11-11 17:00 UTC
    out = migration.windows(utc(2025, 10, 8, 21, 25), utc(2026, 11, 20), now)
    assert out[0][0] == utc(2025, 10, 8, 17)  # local midnight on or before the first reading
    assert out[-1][1] == utc(2026, 11, 11, 17)  # never into the open bucket
    assert all(b - a <= 31 * DAY and b - a >= DAY for a, b in out)
    assert all(a[1] == b[0] for a, b in zip(out, out[1:], strict=False))  # contiguous


def test_windows_are_empty_when_the_history_ends_today():
    now = utc(2026, 11, 12, 5)
    assert migration.windows(utc(2026, 11, 11, 18), utc(2026, 11, 12, 4), now) == []
