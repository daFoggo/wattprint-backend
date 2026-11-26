from scripts.wappi_judges import CRITERIA, combine, prompt


def vote(**kw):
    return {c: kw.get(c, 5) for c in CRITERIA}


def test_combine_majority_pass():
    out = combine([vote(), vote(), vote(correct=2)])
    assert out["verdict"] == "pass"
    assert out["judges"] == 3
    assert out["agree"] is False


def test_combine_drops_invalid_judge():
    out = combine([vote(), None, vote()])
    assert out["judges"] == 2
    assert out["verdict"] == "pass"
    assert out["agree"] is True


def test_combine_all_invalid_is_unjudged():
    out = combine([None, None, None])
    assert out["verdict"] == "unjudged"
    assert out["judges"] == 0


def test_combine_low_correctness_fails_even_if_tone_is_high():
    out = combine([vote(correct=3), vote(correct=3), vote(correct=3)])
    assert out["verdict"] == "fail"


def test_prompt_carries_the_evidence_and_the_date_but_not_who_answered():
    text = prompt("Hôm nay dùng bao nhiêu?", "Hôm nay dùng 5 kWh.", '{"kwh": 5.0}', "2026-11-26")
    assert "Hôm nay dùng bao nhiêu?" in text and "Hôm nay dùng 5 kWh." in text
    assert '{"kwh": 5.0}' in text and "2026-11-26" in text
    assert "tool" not in text.lower() and "model" not in text.lower()


def test_prompt_says_when_nothing_was_read():
    assert "không đọc dữ liệu nào" in prompt("Q", "A")
