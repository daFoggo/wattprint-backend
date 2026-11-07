"""find_skills: cosine search over the catalog chunks a home may see (spec section 6), the top-n
ranking with its choose / none case, and loading a skill with its tools for decide and act."""

import uuid
from typing import Any

from sqlalchemy import select, text

from ...models import Skill, SkillTool, Tool
from ..config.settings import LLM

CFG = LLM["retrieval"]

SEARCH = text("""
WITH visible AS (
    SELECT s.id FROM copilot.skill s
    LEFT JOIN copilot.skill_setting ss ON ss.skill_id = s.id AND ss.home_id = :home
    WHERE s.enabled AND s.embed_status = 'ready' AND 'chat' = ANY (s.triggers)
      AND ((s.home_id IS NULL AND coalesce(ss.enabled, true)) OR s.home_id = :home)
),
best AS (
    SELECT t.skill_id, max(t.sim) AS sim FROM (
        SELECT c.skill_id, 1 - (c.embedding <=> CAST(:v AS vector)) AS sim
        FROM copilot.catalog_chunk c
        WHERE c.skill_id IN (SELECT id FROM visible)
          AND (c.home_id IS NULL OR c.home_id = :home) AND c.embed_status = 'ready'
        ORDER BY c.embedding <=> CAST(:v AS vector) LIMIT 60) t
    GROUP BY t.skill_id
)
SELECT s.id::text AS id, s.code, s.name, s.description, s.mode, s.home_id IS NOT NULL AS own,
       round(b.sim::numeric, 4)::float AS sim
FROM best b JOIN copilot.skill s ON s.id = b.skill_id
ORDER BY b.sim DESC LIMIT :k
""")


async def search(session, home_id: str, vector: list[float], top_k: int | None = None
                 ) -> list[dict[str, Any]]:
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    rows = await session.execute(SEARCH, {"home": uuid.UUID(home_id), "v": str(vector),
                                          "k": top_k or CFG["skill_top_k"]})
    return [dict(r._mapping) for r in rows]


def case_of(candidates: list[dict[str, Any]]) -> str:
    """"choose": the model picks one of the top-n candidates in decide; "none": nothing is
    close enough to ask it (out of scope)."""
    sims = [c["sim"] for c in candidates if c.get("sim") is not None]
    return "choose" if sims and max(sims) >= CFG["choose_min_sim"] else "none"


async def load_skill(session, *, home_id: str, skill_id: str | None = None,
                     code: str | None = None) -> dict[str, Any] | None:
    """A skill this home may use, with its enabled tools in order (presets attached)."""
    q = select(Skill).where(Skill.enabled,
                            (Skill.home_id.is_(None)) | (Skill.home_id == uuid.UUID(home_id)))
    q = q.where(Skill.id == uuid.UUID(skill_id)) if skill_id else q.where(Skill.code == code)
    skill = (await session.execute(q.order_by(Skill.home_id.nulls_last()))).scalars().first()
    if skill is None:
        return None
    links = (await session.execute(
        select(SkillTool, Tool).join(Tool, Tool.id == SkillTool.tool_id)
        .where(SkillTool.skill_id == skill.id, Tool.enabled).order_by(SkillTool.ord))).all()
    return {
        "id": str(skill.id), "code": skill.code, "name": skill.name,
        "description": skill.description, "instructions": skill.instructions, "mode": skill.mode,
        "max_steps": skill.max_steps, "followups": list(skill.followups),
        "household": skill.home_id is not None,
        "tools": [{"name": t.name, "handler": t.handler, "label_vi": t.label_vi,
                   "label_en": t.label_en, "description": t.description,
                   "parameters": t.parameters, "side_effect": t.side_effect,
                   "timeout_ms": t.timeout_ms, "preset": link.preset or {}}
                  for link, t in links],
    }
