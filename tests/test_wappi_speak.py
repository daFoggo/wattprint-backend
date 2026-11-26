from scripts.wappi_speak import speak_lint


def test_lint_passes_plain_short_sentences():
    assert speak_lint("Hôm nay nhà bạn dùng 12 ki lô oát giờ. Nhiều hơn hôm qua một chút.") == []


def test_lint_flags_long_sentence():
    assert "long_sentence" in speak_lint(" ".join(["từ"] * 26) + ".")


def test_lint_flags_parentheses_and_dash_aside():
    assert speak_lint("Máy giặt (ước tính) dùng nhiều — hơn cả tủ lạnh.") == [
        "dash_aside",
        "parentheses",
    ]


def test_lint_flags_crowded_figures_and_markup():
    assert "many_numbers" in speak_lint("Có 1, 2, 3, 4 và 5 thiết bị.")
    assert "markup" in speak_lint("**Nhiều** nhất là tủ lạnh.")
    assert "markup" in speak_lint("- một\n- hai")


def test_lint_keeps_hyphenated_words_and_decimals_clean():
    assert speak_lint("Tủ lạnh-đông dùng 1,5 kWh mỗi ngày.") == []
