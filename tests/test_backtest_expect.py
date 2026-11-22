import pytest

from scripts.backtest_expect import score


def test_score_mape_and_coverage():
    rows = [(100.0, 110.0, 105.0, True), (200.0, 180.0, 210.0, False)]
    got = score(rows)
    assert got["mape_v1"] == pytest.approx((0.10 + 0.10) / 2)
    assert got["mape_ctx"] == pytest.approx((0.05 + 0.05) / 2)
    assert got["coverage"] == pytest.approx(0.5)
    assert got["points"] == 2


def test_score_of_nothing_is_empty():
    assert score([]) == {"points": 0}
