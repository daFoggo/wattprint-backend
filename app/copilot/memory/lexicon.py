"""The household's own words and names, matched to its devices, device types, rooms and terms
(trigram search on copilot_ro.lexicon). Used by rewrite_question to link a question's words."""

from ..agents.state import Candidate
from ..utils.helpers import as_json

MIN_SCORE = 0.6


TOP_PER_KIND = 5


_PRECEDENCE = {"term": 0, "device_type": 1, "device": 2, "room": 2}


LINK_SQL = """
WITH q AS (SELECT copilot_ro.match_key($1) AS k),
m AS (
    SELECT l.source, l.kind, l.ref, l.target, l.phrase,
           strict_word_similarity(l.match_key, q.k) AS score
    FROM copilot_ro.lexicon l, q
    WHERE l.match_key <> '' AND q.k <> ''
),
best AS (
    SELECT DISTINCT ON (source, kind, ref) *
    FROM m WHERE score >= $2
    ORDER BY source, kind, ref, score DESC
)
SELECT b.source, b.kind, b.ref, b.target, b.phrase, b.score,
       coalesce(x.ids, '{}') AS device_ids, coalesce(x.names, '{}') AS device_names
FROM best b
LEFT JOIN LATERAL (
    SELECT array_agg(d.id::text ORDER BY d.name) AS ids,
           array_agg(d.name::text ORDER BY d.name) AS names
    FROM copilot_ro.device d
    WHERE d.deleted_at IS NULL
      AND ((b.kind = 'device' AND d.id::text = b.ref)
           OR (b.kind = 'device_type' AND d.device_type_code = b.ref))
) x ON true
"""


async def link_entities(conn, question: str) -> list[Candidate]:
    """Words -> the home's devices, device types, rooms and terms (trigram on match keys)."""
    rows = await conn.fetch(LINK_SQL, question, MIN_SCORE)
    cands = [
        Candidate(source=r["source"], kind=r["kind"], ref=r["ref"], phrase=r["phrase"],
                  score=round(float(r["score"]), 3), device_ids=list(r["device_ids"]),
                  device_names=list(r["device_names"]),
                  target=as_json(r["target"]))
        for r in rows
    ]
    # best first; among equals a home word, then a type the home has, then a device name
    cands.sort(key=lambda c: (-c.score, _PRECEDENCE[c.source], not c.device_ids))
    out, per_kind = [], {}
    for c in cands:
        per_kind[c.kind] = per_kind.get(c.kind, 0) + 1
        if per_kind[c.kind] <= TOP_PER_KIND:
            out.append(c)
    return out
