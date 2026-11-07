"""Pure parts of the skill registry: chunking and the number grounding check (no database)."""

from app.copilot.skills.chunker import no_tone, sentences, skill_chunks, tool_chunks
from app.copilot.skills.grounding import ungrounded


def test_no_tone_drops_marks_and_d():
    assert no_tone("Bếp tuần qua tốn bao nhiêu ĐIỆN?") == "bep tuan qua ton bao nhieu dien?"


def test_sentences_merge_short_pieces_and_cut_long_ones():
    parts = sentences("Ngắn. Một câu đủ dài để đứng riêng một mình trong chunk này. " + "x " * 300)
    assert parts[0].startswith("Ngắn. Một câu")  # the short piece joined the next
    assert all(len(p) <= 400 for p in parts) and len(parts) >= 2


def test_examples_are_stored_with_and_without_tone_marks():
    chunks = skill_chunks("Báo cáo bếp", "Điện năng của bếp theo thiết bị trong tuần.",
                          ["Bếp tuần qua tốn bao nhiêu điện", "bep hom nay"])
    examples = [c.text for c in chunks if c.kind == "example"]
    assert examples == ["Bếp tuần qua tốn bao nhiêu điện", "bep tuan qua ton bao nhieu dien",
                        "bep hom nay"]  # the toneless one needs no twin
    assert chunks[0].kind == "description" and chunks[0].text.startswith("Báo cáo bếp.")


def test_tool_chunks_include_each_described_argument():
    chunks = tool_chunks("search_price", "Tra giá điện", "Tariff tiers on a day.",
                         {"properties": {"date": {"description": "the day"}, "x": {}}})
    assert [c.kind for c in chunks] == ["tool", "param"]
    assert chunks[1].text == "search_price.date: the day"


def test_grounding_reads_vietnamese_and_english_numbers():
    sources = ['{"amount": 137386, "kwh": 17.25}', "Khoảng thời gian: 04/11/2026"]
    assert ungrounded("Hôm qua 17,25 kWh, tiền 137.386 đ, ngày 04/11/2026.", sources) == []
    assert ungrounded("Tiền 137,386 đ (17.3 kWh).", sources) == []  # rounding allowed
    assert ungrounded("Khoảng 250 kWh.", sources) == ["250"]
    assert ungrounded("Có 2 thiết bị.", sources) == []  # small counts pass


def test_ingress_rate_limits_one_user(monkeypatch):
    import pytest

    from app.copilot.nodes import ingress_node

    monkeypatch.setitem(ingress_node.LIMITS, "messages_per_minute", 2)
    monkeypatch.setattr(ingress_node, "_RECENT", ingress_node.defaultdict(ingress_node.deque))
    ingress_node._rate_limit("u")
    ingress_node._rate_limit("u")
    with pytest.raises(ingress_node.RejectedError) as err:
        ingress_node._rate_limit("u")
    assert err.value.status == 429
    ingress_node._rate_limit("someone else")  # per user
