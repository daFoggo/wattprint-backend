"""skills.yaml + the handler registry → copilot.tool / skill / skill_tool / catalog_chunk.

`sync` is idempotent: unchanged chunks keep their vectors (content_hash), system rows that left
the file are disabled, household rows are never touched. `replace_chunks` is also how the API
embeds a household's skill or its own examples on a system skill.
"""

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete, select

from ...models import CatalogChunk, Skill, SkillTool, Tool
from ..tools.registry import handlers
from .chunker import ChunkIn, content_hash, skill_chunks, tool_chunks

SPEC = Path(__file__).resolve().parents[1] / "config" / "skills.yaml"


def load_spec(path: Path = SPEC) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


async def replace_chunks(session, embedder, chunks: list[ChunkIn], *, skill_id=None, tool_id=None,
                         home_id=None, kinds: tuple[str, ...] | None = None) -> str:
    """Make the stored chunks of one owner (and home) equal `chunks`; embed the new ones."""
    owner = CatalogChunk.skill_id == skill_id if skill_id else CatalogChunk.tool_id == tool_id
    home = CatalogChunk.home_id.is_(None) if home_id is None else CatalogChunk.home_id == home_id
    q = select(CatalogChunk).where(owner, home)
    if kinds:
        q = q.where(CatalogChunk.kind.in_(kinds))
    stored = {c.content_hash: c for c in (await session.execute(q)).scalars()}
    model = getattr(embedder, "model_name", "embedder")
    wanted = {content_hash(model, c.text): c for c in chunks}
    for h, row in stored.items():
        if h not in wanted:
            await session.delete(row)
    fresh = []
    for h, c in wanted.items():
        row = stored.get(h)
        if row is None:
            row = CatalogChunk(skill_id=skill_id, tool_id=tool_id, home_id=home_id, kind=c.kind,
                               ord=c.ord, text=c.text, content_hash=h, embed_status="pending")
            session.add(row)
        else:
            row.ord = c.ord
        if row.embed_status != "ready":
            fresh.append(row)
    if fresh:
        try:
            vectors = await embedder.embed([r.text for r in fresh])
        except Exception:  # the row stays, unsearchable, until /reembed
            for r in fresh:
                r.embed_status = "failed"
            await session.flush()
            return "failed"
        for r, v in zip(fresh, vectors, strict=True):
            r.embedding, r.embed_status = v, "ready"
    await session.flush()
    return "ready"


def _changed(row, fields: dict[str, Any]) -> bool:
    changed = False
    for k, v in fields.items():
        if getattr(row, k) != v:
            setattr(row, k, v)
            changed = True
    return changed


async def sync(session, embedder, spec: dict[str, Any] | None = None) -> dict[str, int]:
    spec = spec or load_spec()
    registry = handlers()
    tools: dict[str, Tool] = {t.name: t for t in (await session.execute(select(Tool))).scalars()}
    for t in spec["tools"]:
        h = registry[t["name"]]  # KeyError: a tool in the file without a handler in code
        fields = {"label_vi": t["label_vi"], "label_en": t["label_en"],
                  "description": " ".join(t["description"].split()), "category": t["category"],
                  "handler": h.name, "parameters": h.schema(),
                  "presettable": t.get("presettable", []), "side_effect": h.side_effect,
                  "user_selectable": t.get("user_selectable", False),
                  "timeout_ms": t.get("timeout_ms", 5000), "enabled": True}
        row = tools.get(t["name"])
        if row is None:
            row = tools[t["name"]] = Tool(name=t["name"], **fields)
            session.add(row)
        elif _changed(row, fields):
            row.version += 1
        await session.flush()
        await replace_chunks(session, embedder, tool_chunks(row.name, row.label_vi,
                                                            row.description, row.parameters),
                             tool_id=row.id)
    names = {t["name"] for t in spec["tools"]}
    for name, row in tools.items():
        if name not in names:
            row.enabled = False

    skills = {s.code: s for s in (await session.execute(
        select(Skill).where(Skill.home_id.is_(None)))).scalars()}
    for s in spec["skills"]:
        fields = {"name": s["name"], "description": " ".join(s["description"].split()),
                  "instructions": " ".join((s.get("instructions") or "").split()),
                  "mode": s.get("mode", "agent"), "triggers": s.get("triggers", ["chat"]),
                  "schedule": s.get("schedule"), "max_steps": s.get("max_steps", 4),
                  "followups": s.get("followups", []), "enabled": True}
        row = skills.get(s["code"])
        if row is None:
            row = skills[s["code"]] = Skill(code=s["code"], **fields)
            session.add(row)
        elif _changed(row, fields):
            row.version += 1
        await session.flush()
        await session.execute(delete(SkillTool).where(SkillTool.skill_id == row.id))
        for i, link in enumerate(s["tools"]):
            name, preset = (link, {}) if isinstance(link, str) else (link["tool"], link["preset"])
            session.add(SkillTool(skill_id=row.id, tool_id=tools[name].id, ord=i, preset=preset))
        row.embed_status = await replace_chunks(
            session, embedder, skill_chunks(row.name, row.description, s.get("examples", [])),
            skill_id=row.id)
    codes = {s["code"] for s in spec["skills"]}
    for code, row in skills.items():
        if code not in codes:
            row.enabled = False
    await session.commit()
    return {"tools": len(spec["tools"]), "skills": len(spec["skills"])}
