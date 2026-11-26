from datetime import date
from types import SimpleNamespace

from scripts.wappi_scenarios import GROUPS, SCENARIOS, evaluate

BILL = SimpleNamespace(amount_total=1000000, amount_before_vat=925926, today_kwh=10.0)
T = {"bill": BILL}


def result(tools=(), watches=(), error=None):
    return {"tools": [(n, True) for n in tools], "watches": list(watches), "error": error}


def test_ids_unique_and_groups_are_wide_enough():
    assert len({s.id for s in SCENARIOS}) == len(SCENARIOS) >= 60
    assert all(len(items) >= 3 for items in GROUPS.values())
    assert {"history", "estimate", "cause", "advice", "day_hour", "tariff_doc"} <= set(GROUPS)


def test_third_of_scenarios_are_held_out_in_every_group():
    held = [s for s in SCENARIOS if s.split == "held"]
    assert len(held) / len(SCENARIOS) >= 0.3
    assert all(any(s.split == "held" for s in SCENARIOS if s.group == g) for g in GROUPS)


def test_tariff_questions_name_a_document_or_expect_unknown():
    for s in SCENARIOS:
        if s.group == "tariff_doc":
            assert s.expect.get("mentions") or s.expect.get("unknown")


def test_evaluate_tool_and_figure_checks():
    ok = evaluate({"tools": ["bill_forecast"]}, "Khoảng 1.000.000 đ.", result(["bill_forecast"]), T)
    assert ok == []
    assert evaluate({"tools": ["bill_forecast"]}, "Khoảng 1 triệu.", result(), T) == [
        "tool_missing"
    ]
    assert evaluate({"figure": "bill"}, "Bạn nợ 500.000 đ", result(), T) == ["figure_wrong"]
    assert evaluate({"no_figure": True}, "Vàng 80.000.000 đ", result(), T) == ["figure_invented"]


def test_evaluate_reads_so_dien_as_kwh():
    ok = evaluate({"figure": "kwh_today"}, "Hôm nay bạn dùng 10 số điện.", result(), T)
    assert ok == []
    assert evaluate({"figure": "kwh_today"}, "Hôm nay bạn dùng 30 số điện.", result(), T) == [
        "figure_wrong"
    ]


def test_evaluate_unknown_and_empty_answers():
    assert evaluate({"unknown": True}, "Điều 99 nói về giá.", result(), T) == [
        "invented_instead_of_unknown"
    ]
    assert evaluate({"unknown": True}, "Mình chưa có tài liệu đó.", result(), T) == []
    assert evaluate({}, "", result(), T) == ["no_answer"]
    assert evaluate({}, "x", result(error="llm"), T) == ["no_answer"]


def test_evaluate_alert_checks_read_the_rows_not_the_words():
    row = {"metric": "bill_vnd", "op": "gt", "threshold": 1_000_000.0, "device_id": None}
    assert (
        evaluate({"watch": ["bill_vnd", "gt", 1000000]}, "Đã đặt.", result(watches=[row]), T) == []
    )
    assert evaluate({"watch": ["bill_vnd", "gt", 1000000]}, "Đã đặt.", result(), T) == [
        "watch_missing"
    ]
    assert evaluate({"no_watch": True}, "Bạn muốn ngưỡng nào?", result(watches=[row]), T) == [
        "watch_created"
    ]


def test_today_is_a_date():
    assert date.today().year >= 2026
