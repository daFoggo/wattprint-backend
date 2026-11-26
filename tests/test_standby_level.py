from app.modules.copilot.services.tools import standby_level


def test_steady_nights_have_no_shift():
    assert standby_level([100.0] * 14) == (100.0, None)


def test_a_rise_is_quoted_at_the_recent_level_and_reported():
    level, shift = standby_level([120.0] * 7 + [380.0] * 7)
    assert level == 380.0
    assert shift == {"earlier_watts": 120, "recent_watts": 380}


def test_too_few_earlier_nights_or_a_small_move_report_nothing():
    assert standby_level([120.0, 120.0, 380.0, 380.0, 380.0, 380.0, 380.0, 380.0, 380.0])[1] is None
    assert standby_level([100.0] * 7 + [110.0] * 7)[1] is None
