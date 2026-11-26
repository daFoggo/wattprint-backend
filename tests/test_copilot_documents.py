import unicodedata
import zlib
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models import Document
from app.modules.copilot.services import documents, tools

PREFIX = "TEST "


def fake_embed(texts: list[str]) -> list[list[float]]:
    """A bag of hashed words: texts that share words are close, texts that share none are not."""
    out = []
    for t in texts:
        v = [0.0] * 1024
        for w in t.lower().split():
            v[zlib.crc32(w.encode()) % 1024] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        out.append([x / norm for x in v])
    return out


async def fake(texts: list[str]) -> list[list[float]]:
    return fake_embed(texts)


def meta(title, kind="tariff", published="2025-05-09"):
    return {"title": PREFIX + title, "doc_type": kind, "published_at": published, "version": "v"}


async def store():
    async with SessionLocal() as s:
        await documents.ingest(
            s,
            meta("Quyết định 1279/QĐ-BCT", published="2025-05-09"),
            "Biểu giá sinh hoạt sáu bậc. Bậc 1 là 1.984 đồng mỗi kWh.",
            fake,
        )
        await documents.ingest(
            s,
            meta("Quyết định 2892/QĐ-BCT", published="2026-10-31"),
            "Biểu giá sinh hoạt năm bậc. Bậc 1 là 1.901 đồng mỗi kWh.",
            fake,
        )
        await documents.ingest(
            s,
            meta("Luật dữ liệu cá nhân", kind="other", published="2025-12-01"),
            "Luật Bảo vệ dữ liệu cá nhân có hiệu lực từ ngày 1 tháng 1 năm 2026.",
            fake,
        )
        await s.commit()


async def clean():
    async with SessionLocal() as s:
        await s.execute(delete(Document).where(Document.title.like(PREFIX + "%")))
        await s.commit()


def test_chunk_respects_size_and_carries_overlap():
    body = "\n".join(f"Điều {i}. " + "từ " * 60 for i in range(12))
    parts = documents.chunk(body, size=400, overlap=60)
    assert len(parts) > 3
    assert all(len(p) <= 400 for p in parts)
    assert parts[1].split()[0] in parts[0]
    assert "Điều 11." in parts[-1]


def test_chunk_splits_a_line_longer_than_a_chunk_and_skips_blank_lines():
    parts = documents.chunk("a " * 500 + "\n\n\nend", size=200, overlap=40)
    assert all(len(p) <= 200 for p in parts)
    assert parts[-1].endswith("end")
    assert documents.chunk("   \n\n") == []


def test_parse_source_reads_front_matter_and_body():
    meta_, body = documents.parse_source("---\ntitle: A: b\ndoc_type: tariff\n---\nNội dung\n")
    assert meta_ == {"title": "A: b", "doc_type": "tariff"}
    assert body == "Nội dung"


def passage(title, kind, published):
    return documents.Passage("i", title, None, None, kind, published, "x", 1.0)


OLD_TITLE = "Quyết định 1279/QĐ-BCT về giá bán điện (áp dụng từ 10/05/2025, biểu giá 6 bậc)"


def test_newest_tariff_only_drops_the_older_decision_unless_named():
    from datetime import date

    old = passage(OLD_TITLE, "tariff", date(2025, 5, 9))
    new = passage(
        "Quyết định 2892/QĐ-BCT về giá bán điện (áp dụng từ 01/11/2026)",
        "tariff",
        date(2026, 10, 31),
    )
    law = passage("Luật", "other", date(2025, 12, 1))
    assert documents.newest_tariff_only([old, new, law], "giá bậc 1") == [new, law]
    assert documents.newest_tariff_only([old, new], "giá theo quyết định 1279") == [old, new]
    assert documents.newest_tariff_only([law], "x") == [law]
    assert documents.newest_tariff_only([old, new], "giá năm 2025 là bao nhiêu") == [old, new]
    assert documents.newest_tariff_only([old, new], "trước tháng 11 giá bậc 1") == [old, new]
    assert documents.newest_tariff_only([old, new], "the old six-tier price") == [old, new]
    decomposed = unicodedata.normalize("NFD", "trước tháng 11 giá bậc 1")
    assert documents.newest_tariff_only([old, new], decomposed) == [old, new]
    # Words that only contain a cue, a number that only contains a number, a date in the title.
    for question in (
        "What is the household electricity tariff now?",
        "Giá điện bậc 1 cũng tăng à?",
        "Giá điện trước thuế là bao nhiêu?",
        "Price before tax and VAT?",
        "Bậc 1 đến 100 kWh giá bao nhiêu?",
        "Giá điện ngày 10 hôm nay?",
    ):
        assert documents.newest_tariff_only([old, new], question) == [new], question


async def test_search_prefers_newer_tariff_document():
    await clean()
    await store()
    try:
        async with SessionLocal() as s:
            got = await documents.search(
                s, "Bậc 1 giá điện sinh hoạt bao nhiêu", embedder=fake, max_distance=0.95
            )
        titles = [p.title for p in got]
        assert PREFIX + "Quyết định 2892/QĐ-BCT" in titles
        assert PREFIX + "Quyết định 1279/QĐ-BCT" not in titles
        async with SessionLocal() as s:
            both = await documents.search(
                s, "Bậc 1 theo quyết định 1279 là bao nhiêu", embedder=fake, max_distance=0.95
            )
        assert PREFIX + "Quyết định 1279/QĐ-BCT" in [p.title for p in both]
    finally:
        await clean()


async def test_search_empty_when_nothing_matches():
    await clean()
    await store()
    try:
        async with SessionLocal() as s:
            got = await documents.search(s, "xyzzy plugh quux", embedder=fake, max_distance=0.95)
        assert [p for p in got if p.title.startswith(PREFIX)] == []
        async with SessionLocal() as s:
            assert await documents.search(s, "?! ..", embedder=fake, max_distance=0.95) == []
    finally:
        await clean()


async def test_tool_returns_passages_and_source_keys(monkeypatch, make_member):
    await clean()
    await store()
    real = documents.search

    async def search(s, question, k=4, embedder=documents.embed):
        return await real(s, question, k, embedder=fake, max_distance=0.95)

    monkeypatch.setattr(documents, "search", search)
    me = await make_member("owner")
    try:
        async with SessionLocal() as s:
            ctx = tools.Ctx(s, me.home_id, datetime.now(UTC), "vi")
            out = await tools.search_documents(ctx, "Luật bảo vệ dữ liệu cá nhân hiệu lực khi nào")
        assert out.data["passages"] and "1 tháng 1 năm 2026" in out.data["passages"][0]["text"]
        assert out.tier == "document"  # quoted text, not a measurement, whatever the document is
        assert out.sources and all(k in tools.DOC_SOURCES for k in out.sources)
        title, url = tools.DOC_SOURCES[out.sources[0]]
        assert title["vi"].startswith(PREFIX) and url
    finally:
        await clean()


async def test_tool_says_so_when_nothing_matches(monkeypatch, make_member):
    async def search(s, question, k=4, embedder=documents.embed):
        return []

    monkeypatch.setattr(documents, "search", search)
    me = await make_member("owner")
    async with SessionLocal() as s:
        out = await tools.search_documents(
            tools.Ctx(s, me.home_id, datetime.now(UTC), "vi"), "Điều 99 Luật Điện lực"
        )
    assert out.data["passages"] == [] and "do not have" in out.data["note"]


@pytest.fixture
def both_keys(monkeypatch):
    monkeypatch.setattr(documents.settings, "copilot_llm_order", "openrouter,astralx")
    monkeypatch.setattr(documents.settings, "openrouter_api_key", "k1")
    monkeypatch.setattr(documents.settings, "astralx_api_key", "k2")


async def test_embed_uses_openrouter_first_and_astralx_when_it_fails(monkeypatch, both_keys):
    asked = []

    async def call(base_url, key, model, texts):
        asked.append(model)
        if "openrouter" in base_url:
            raise httpx.ConnectError("down")
        return [[1.0] * 1024 for _ in texts]

    monkeypatch.setattr(documents, "_call", call)
    got = await documents.embed(["a", "b"])
    assert len(got) == 2
    assert asked == [
        documents.settings.openrouter_embed_model,
        documents.settings.astralx_embed_model,
    ]


async def test_embed_stops_at_the_first_provider_that_answers(monkeypatch, both_keys):
    asked = []

    async def call(base_url, key, model, texts):
        asked.append(model)
        return [[0.5] * 1024]

    monkeypatch.setattr(documents, "_call", call)
    await documents.embed(["a"])
    assert asked == [documents.settings.openrouter_embed_model]


async def test_embed_skips_a_provider_without_a_key_and_fails_loudly_when_none_answer(
    monkeypatch, both_keys
):
    monkeypatch.setattr(documents.settings, "openrouter_api_key", "")
    seen = []

    async def call(base_url, key, model, texts):
        seen.append(key)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(documents, "_call", call)
    with pytest.raises(httpx.ConnectError):
        await documents.embed(["a"])
    assert seen == ["k2"]
    monkeypatch.setattr(documents.settings, "astralx_api_key", "")
    with pytest.raises(LookupError):
        await documents.embed(["a"])


async def test_embed_rejects_vectors_of_the_wrong_size(monkeypatch, both_keys):
    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"embedding": [0.1] * 768}]}

    class Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            return Reply()

    monkeypatch.setattr(documents.httpx, "AsyncClient", Client)
    with pytest.raises(ValueError, match="wrong shape"):
        await documents._call("http://x", "k", "m", ["a"])


async def test_a_judge_that_answers_null_is_dropped_not_fatal():
    from scripts.wappi_judges import judge

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": None}

    class Client:
        async def post(self, *a, **kw):
            return Reply()

    assert await judge(Client(), "m", "user text") is None
