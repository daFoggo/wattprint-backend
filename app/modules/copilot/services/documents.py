import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Chunk, Document
from app.models.knowledge import EMBEDDING_DIM

from . import llm

log = logging.getLogger("copilot.documents")
EMBEDDING_MODEL = "baai/bge-m3"  # what the stored vectors are, whichever provider made them

POOL = 20  # candidates each ranking contributes before they are fused
RRF = 60  # reciprocal rank fusion constant
# Cosine distance above which a chunk is not about the question.
# shortcut: calibrated on 28 questions over 14 chunks (2026-11-26: related 0.19-0.48, the English
# ones nearest the line; unrelated 0.50-0.67); recalibrate when the corpus grows.
MAX_DISTANCE = 0.49
# A decision's number (1279 in "1279/QĐ-BCT"), never a date in its title ("10/05").
CODE = re.compile(r"\b(\d+)(?:/\d{4})?/[A-ZĐ]{2,}")
# Whole words that mean "an earlier decision"; "trước thuế" / "before tax" is not one.
PAST = re.compile(
    r"\b(?:trước(?!\s+thuế)|cũ|xưa|old|previous|earlier|before(?!\s+(?:tax|vat)))\b", re.IGNORECASE
)

SEARCH = text(
    """
    WITH fts AS (
        SELECT c.id, row_number() OVER (ORDER BY ts_rank(c.tsv, q) DESC) AS r
        FROM public.tb_chunk c, to_tsquery('simple', public.immutable_unaccent(:ors)) q
        WHERE c.tsv @@ q
        ORDER BY ts_rank(c.tsv, q) DESC
        LIMIT :pool
    ), vec AS (
        SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> CAST(:v AS vector)) AS r
        FROM public.tb_chunk c
        ORDER BY c.embedding <=> CAST(:v AS vector)
        LIMIT :pool
    ), fused AS (
        SELECT coalesce(fts.id, vec.id) AS id,
               coalesce(1.0 / (:rrf + fts.r), 0) + coalesce(1.0 / (:rrf + vec.r), 0) AS score
        FROM fts FULL JOIN vec ON fts.id = vec.id
    )
    SELECT c.id, d.id, c.body, d.title, d.source_url, d.version, d.doc_type, d.published_at,
           f.score
    FROM fused f
    JOIN public.tb_chunk c ON c.id = f.id
    JOIN public.tb_document d ON d.id = c.document_id
    WHERE c.embedding <=> CAST(:v AS vector) <= :max_dist
    ORDER BY f.score DESC, c.ord
    """
)


@dataclass(frozen=True)
class Passage:
    doc_id: str
    title: str
    url: str | None
    version: str | None
    doc_type: str
    published_at: date | None
    text: str
    score: float


def chunk(body: str, size: int = 900, overlap: int = 120) -> list[str]:
    """Paragraph-aware pieces of at most `size` characters; each starts with the end of the last."""
    room = size - overlap - 1  # a line plus the carried tail still fits
    lines: list[str] = []
    for line in filter(None, (raw.strip() for raw in body.splitlines())):
        while len(line) > room:
            cut = line.rfind(" ", 0, room)
            cut = cut if cut > 0 else room
            lines.append(line[:cut].strip())
            line = line[cut:].strip()
        if line:
            lines.append(line)
    out: list[str] = []
    cur = ""
    for line in lines:
        if cur and len(cur) + 1 + len(line) > size:
            out.append(cur)
            tail = cur[-overlap:]
            cur = tail[tail.find(" ") + 1 :] if " " in tail else tail
        cur = f"{cur}\n{line}" if cur else line
    return [*out, cur] if cur else out


def parse_source(raw: str) -> tuple[dict[str, str], str]:
    """A source file: `key: value` lines between two `---` lines, then the text."""
    _, head, body = raw.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in head.strip().splitlines() if ": " in line)
    return meta, body.strip()


async def _call(base_url: str, key: str, model: str, texts: list[str]) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=httpx.Timeout(settings.copilot_llm_timeout_s, connect=5.0),
    ) as client:
        body = {"model": model, "input": texts}
        if base_url == settings.openrouter_base_url:
            body["provider"] = llm.OPENROUTER_PRIVACY
        r = await client.post("/embeddings", json=body)
        r.raise_for_status()
        vectors = [d["embedding"] for d in r.json()["data"]]
    if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIM for v in vectors):
        raise ValueError(f"{model} answered vectors of the wrong shape")
    return vectors


def providers() -> list[tuple[str, str, str]]:
    """(base_url, key, model) in the order the chat providers are tried, those with a key."""
    known = {
        "openrouter": (settings.openrouter_base_url, settings.openrouter_api_key),
        "astralx": (settings.astralx_base_url, settings.astralx_api_key),
    }
    models = {
        "openrouter": settings.openrouter_embed_model,
        "astralx": settings.astralx_embed_model,
    }
    names = [n.strip() for n in settings.copilot_llm_order.split(",")]
    return [(*known[n], models[n]) for n in names if n in known and known[n][1]]


async def embed(texts: list[str]) -> list[list[float]]:
    """From the first provider that answers; a failing one hands over to the next, as chat does.

    shortcut: the tokens spent are not recorded in ai_message.usage (about 15 a question, 1e-7 USD);
    record them when the model costs more or questions get long.
    """
    last: Exception = LookupError("no embedding provider has a key")
    for base_url, key, model in providers():
        try:
            return await _call(base_url, key, model, texts)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            log.warning("embeddings from %s failed: %r", model, e)
            last = e
    raise last


def literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def newest_tariff_only(found: list[Passage], question: str) -> list[Passage]:
    """Tariff decisions replace each other: an older one answers when the question names it
    (its number or year) or asks about the past."""
    tariffs = [p for p in found if p.doc_type == "tariff" and p.published_at]
    if not tariffs:
        return found
    newest = max(p.published_at for p in tariffs)

    question = unicodedata.normalize("NFC", question)  # a keyboard may send accents as marks
    past = bool(PAST.search(question))
    numbers = set(re.findall(r"\d+", question))  # whole numbers, so "100" is not "10"

    def named(p: Passage) -> bool:
        years = [str(p.published_at.year)] if p.published_at else []
        return past or any(n in numbers for n in [*CODE.findall(p.title), *years])

    return [
        p
        for p in found
        if p.doc_type != "tariff" or p.published_at == newest or p.published_at is None or named(p)
    ]


async def search(
    s: AsyncSession,
    question: str,
    k: int = 4,
    embedder=embed,
    max_distance: float = MAX_DISTANCE,
) -> list[Passage]:
    words = sorted(set(re.findall(r"\w{3,}", question.lower())))
    if not words:
        return []
    (vector,) = await embedder([question])
    rows = (
        await s.execute(
            SEARCH,
            {
                "ors": " | ".join(words),
                "v": literal(vector),
                "pool": POOL,
                "rrf": RRF,
                "max_dist": max_distance,
            },
        )
    ).all()
    found = [
        Passage(str(doc), title, url, version, kind, published, body, float(score))
        for _, doc, body, title, url, version, kind, published, score in rows
    ]
    return newest_tariff_only(found, question)[:k]


async def ingest(s: AsyncSession, meta: dict[str, str], body: str, embedder=embed) -> int:
    """Store one document (replacing the one with the same title); returns its chunk count."""
    await s.execute(delete(Document).where(Document.title == meta["title"]))
    parts = chunk(body)
    vectors = await embedder(parts)
    doc = Document(
        title=meta["title"],
        doc_type=meta["doc_type"],
        lang=meta.get("lang", "vi"),
        source_url=meta.get("source_url") or None,
        version=meta.get("version"),
        license_note=meta.get("license_note"),
        published_at=date.fromisoformat(meta["published_at"]) if meta.get("published_at") else None,
    )
    s.add(doc)
    await s.flush()
    s.add_all(
        Chunk(
            document_id=doc.id,
            ord=i,
            body=part,
            embedding=vector,
            embedding_model=EMBEDDING_MODEL,
            token_count=len(part.split()),
        )
        for i, (part, vector) in enumerate(zip(parts, vectors, strict=True))
    )
    await s.flush()
    return len(parts)
