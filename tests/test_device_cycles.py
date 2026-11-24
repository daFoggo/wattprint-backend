from datetime import UTC, datetime, timedelta

from app.modules.insight.services.cycles import KEEP, since_for

UNTIL = datetime(2026, 11, 23, tzinfo=UTC)


def test_first_pass_reads_back_to_keep():
    assert since_for(None, None, UNTIL) == UNTIL - KEEP


def test_a_device_whose_runs_start_recently_is_filled_back():
    oldest, newest = UNTIL - timedelta(days=30), UNTIL - timedelta(hours=2)
    assert since_for(oldest, newest, UNTIL) == UNTIL - KEEP


def test_a_device_with_full_history_goes_on_from_its_last_run():
    oldest, newest = UNTIL - KEEP, UNTIL - timedelta(hours=2)
    assert since_for(oldest, newest, UNTIL) == newest


def test_keep_covers_sixty_days():
    assert KEEP >= timedelta(days=60)
