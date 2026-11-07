"""/api/v1/copilot: skills (system and household), tools, "try", and long-term memory.

Members read; the home's owner writes. A household builds skills from the user-selectable tools
and may only narrow them (presets); saving re-chunks and embeds the skill before returning.
"""

import re
import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, func, select

from ..copilot.config.settings import LLM
from ..copilot.skills import retrieval
from ..copilot.skills.catalog_sync import replace_chunks
from ..copilot.skills.chunker import example_chunks, no_tone, skill_chunks
from ..copilot.tools.registry import handlers
from ..dependencies import CurrentUser, DbSession
from ..models import (
    CatalogChunk,
    Device,
    Home,
    HomeMemory,
    SessionSummary,
    Skill,
    SkillSetting,
    SkillTool,
    Tool,
)
from ..schemas.copilot_skills import (
    EnabledIn,
    ExamplesIn,
    MemoryOut,
    SkillIn,
    SkillOut,
    SkillPatch,
    ToolOut,
    TryIn,
    TryOut,
)
from .common import require_home
from .copilot import Context, _owner_home, _unprocessable

router = APIRouter(prefix="/copilot", tags=["copilot"])
LIMITS = LLM["limits"]
_URL = re.compile(r"https?://|www\.", re.I)


def _as_written(chunks: list[CatalogChunk]) -> list[CatalogChunk]:
    """Each example once: hide the no-tone twin the chunker adds to an example with tones."""
    twins = {no_tone(c.text) for c in chunks if no_tone(c.text) != c.text}
    return [c for c in chunks if c.text not in twins]


async def _examples(db, skill_id: uuid.UUID, home_id: uuid.UUID | None, own_only=False):
    q = select(CatalogChunk).where(CatalogChunk.skill_id == skill_id,
                                   CatalogChunk.kind == "example")
    q = q.where(CatalogChunk.home_id == home_id) if own_only else q.where(
        (CatalogChunk.home_id.is_(None)) | (CatalogChunk.home_id == home_id))
    return _as_written(list((await db.execute(
        q.order_by(CatalogChunk.home_id.nulls_first(), CatalogChunk.ord))).scalars()))


async def _skill_out(db, skill: Skill, home_id: uuid.UUID) -> SkillOut:
    links = (await db.execute(select(SkillTool, Tool).join(Tool, Tool.id == SkillTool.tool_id)
                              .where(SkillTool.skill_id == skill.id).order_by(SkillTool.ord))).all()
    enabled = skill.enabled
    if skill.home_id is None:
        setting = await db.get(SkillSetting, (home_id, skill.id))
        enabled = enabled and (setting is None or setting.enabled)
    return SkillOut(
        id=skill.id, code=skill.code, name=skill.name, description=skill.description,
        instructions=skill.instructions, mode=skill.mode, triggers=list(skill.triggers),
        household=skill.home_id is not None, enabled=enabled, embed_status=skill.embed_status,
        tools=[{"name": t.name, "label_vi": t.label_vi, "label_en": t.label_en,
                "side_effect": t.side_effect, "preset": link.preset} for link, t in links],
        examples=[{"id": c.id, "text": c.text, "mine": c.home_id is not None}
                  for c in await _examples(db, skill.id, home_id)],
        followups=list(skill.followups))


async def _visible(db, skill_id: uuid.UUID, home_id: uuid.UUID) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.home_id not in (None, home_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "skill not found")
    return skill


async def _own(db, skill_id: uuid.UUID, home_id: uuid.UUID) -> Skill:
    skill = await _visible(db, skill_id, home_id)
    if skill.home_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "system skills are changed in the code; copy it to edit your own")
    return skill


async def _checked_tools(db, home_id: uuid.UUID, tools) -> list[tuple[Tool, dict]]:
    out = []
    devices = {str(d) for d in (await db.execute(
        select(Device.id).where(Device.home_id == home_id, Device.deleted_at.is_(None)))).scalars()}
    for link in tools:
        tool = await db.scalar(select(Tool).where(Tool.name == link.tool))
        if tool is None or not tool.enabled or not tool.user_selectable:
            raise _unprocessable(f"tools: {link.tool} is not a tool households can use")
        extra = set(link.preset) - set(tool.presettable)
        if extra:
            raise _unprocessable(f"tools.{link.tool}.preset: cannot fix {sorted(extra)}")
        model = handlers()[tool.handler].args
        for key, value in link.preset.items():
            try:
                TypeAdapter(model.model_fields[key].annotation).validate_python(value)
            except ValidationError:
                raise _unprocessable(f"tools.{link.tool}.preset.{key}: invalid value") from None
            ids = value if isinstance(value, list) else [value]
            if key in ("device_ids", "device_id") and value and not set(map(str, ids)) <= devices:
                raise _unprocessable(f"tools.{link.tool}.preset.{key}: not a device of your home")
        out.append((tool, link.preset))
    return out


def _code(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", no_tone(name)).strip("_")[:50] or "skill"
    return slug if slug[0].isalpha() else f"s_{slug}"


def _check_text(body) -> None:
    if body.instructions and _URL.search(body.instructions):
        raise _unprocessable("instructions: no links")
    for e in body.examples or []:
        if not 1 <= len(e.strip()) <= 200:
            raise _unprocessable("examples: each 1 to 200 characters")


async def _save(db, ctx, skill: Skill, tools, home_id: uuid.UUID, examples: list[str]) -> None:
    if tools is not None:
        checked = await _checked_tools(db, home_id, tools)
        await db.execute(delete(SkillTool).where(SkillTool.skill_id == skill.id))
        for i, (tool, preset) in enumerate(checked):
            db.add(SkillTool(skill_id=skill.id, tool_id=tool.id, ord=i, preset=preset))
    skill.embed_status = await replace_chunks(
        db, ctx.embedder(), skill_chunks(skill.name, skill.description, examples),
        skill_id=skill.id, home_id=home_id)
    await db.commit()


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    found = (await db.execute(
        select(Skill).where(((Skill.home_id.is_(None)) & Skill.enabled)
                            | (Skill.home_id == home_id))
        .order_by(Skill.home_id.nulls_last(), Skill.name))).scalars().all()
    return [await _skill_out(db, s, home_id) for s in found if "event" not in s.triggers]


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(body: SkillIn, user: CurrentUser, db: DbSession, ctx: Context):
    home_id = await _owner_home(db, user)
    _check_text(body)
    count = await db.scalar(select(func.count()).select_from(Skill)
                            .where(Skill.home_id == home_id))
    if count >= LIMITS["household_skills"]:
        raise _unprocessable(f"a home has at most {LIMITS['household_skills']} skills")
    code, n = _code(body.name), 1
    while await db.scalar(select(Skill.id).where(Skill.home_id == home_id, Skill.code == code)):
        n += 1
        code = f"{_code(body.name)[:45]}_{n}"
    skill = Skill(home_id=home_id, code=code, name=body.name, description=body.description,
                  instructions=body.instructions, followups=body.followups, created_by=user.id)
    db.add(skill)
    await db.flush()
    await _save(db, ctx, skill, body.tools, home_id, body.examples)
    return await _skill_out(db, skill, home_id)


@router.get("/skills/{skill_id}", response_model=SkillOut)
async def get_skill(skill_id: uuid.UUID, user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    return await _skill_out(db, await _visible(db, skill_id, home_id), home_id)


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def patch_skill(skill_id: uuid.UUID, body: SkillPatch, user: CurrentUser, db: DbSession,
                      ctx: Context):
    home_id = await _owner_home(db, user)
    skill = await _own(db, skill_id, home_id)
    _check_text(body)
    for field in ("name", "description", "instructions", "followups"):
        if getattr(body, field) is not None:
            setattr(skill, field, getattr(body, field))
    examples = body.examples or [c.text for c in await _examples(db, skill.id, home_id, True)]
    skill.version += 1
    await _save(db, ctx, skill, body.tools, home_id, examples)
    return await _skill_out(db, skill, home_id)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: uuid.UUID, user: CurrentUser, db: DbSession):
    home_id = await _owner_home(db, user)
    await db.delete(await _own(db, skill_id, home_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/skills/{skill_id}/enabled", response_model=SkillOut)
async def toggle_skill(skill_id: uuid.UUID, body: EnabledIn, user: CurrentUser, db: DbSession):
    home_id = await _owner_home(db, user)
    skill = await _visible(db, skill_id, home_id)
    if skill.home_id is None:
        setting = await db.get(SkillSetting, (home_id, skill.id))
        if setting is None:
            db.add(SkillSetting(home_id=home_id, skill_id=skill.id, enabled=body.enabled))
        else:
            setting.enabled = body.enabled
    else:
        skill.enabled = body.enabled
    await db.commit()
    return await _skill_out(db, skill, home_id)


@router.post("/skills/{skill_id}/examples", response_model=SkillOut)
async def add_examples(skill_id: uuid.UUID, body: ExamplesIn, user: CurrentUser, db: DbSession,
                       ctx: Context):
    """A home's own phrasing, on its skill or a system one (only this home sees it)."""
    home_id = await _owner_home(db, user)
    skill = await _visible(db, skill_id, home_id)
    mine = [c.text for c in await _examples(db, skill.id, home_id, own_only=True)]
    texts = [*mine, *(e.strip() for e in body.examples if e.strip() not in mine)]
    if len(texts) > LIMITS["examples_per_skill"]:
        raise _unprocessable(f"at most {LIMITS['examples_per_skill']} examples")
    if skill.home_id is not None:
        await replace_chunks(db, ctx.embedder(), skill_chunks(skill.name, skill.description, texts),
                             skill_id=skill.id, home_id=home_id)
    else:
        await replace_chunks(db, ctx.embedder(), example_chunks(texts), skill_id=skill.id,
                             home_id=home_id, kinds=("example",))
    await db.commit()
    return await _skill_out(db, skill, home_id)


@router.delete("/skills/{skill_id}/examples/{chunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_example(skill_id: uuid.UUID, chunk_id: int, user: CurrentUser, db: DbSession):
    home_id = await _owner_home(db, user)
    chunk = await db.get(CatalogChunk, chunk_id)
    if chunk is None or chunk.skill_id != skill_id or chunk.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "example not found (only your own)")
    await db.execute(delete(CatalogChunk).where(
        CatalogChunk.skill_id == skill_id, CatalogChunk.home_id == home_id,
        CatalogChunk.kind == "example", CatalogChunk.text.in_([chunk.text, no_tone(chunk.text)])))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/skills/{skill_id}/copy", response_model=SkillOut,
             status_code=status.HTTP_201_CREATED)
async def copy_skill(skill_id: uuid.UUID, user: CurrentUser, db: DbSession, ctx: Context):
    home_id = await _owner_home(db, user)
    src = await _visible(db, skill_id, home_id)
    links = (await db.execute(select(SkillTool, Tool).join(Tool, Tool.id == SkillTool.tool_id)
                              .where(SkillTool.skill_id == src.id))).all()
    if src.mode != "agent" or not all(t.user_selectable for _, t in links):
        raise _unprocessable("only chat skills built from household tools can be copied")
    examples = [c.text for c in await _examples(db, src.id, home_id)][:30]
    body = SkillIn(name=f"{src.name} (nhà tôi)"[:60], description=src.description,
                   instructions=src.instructions, examples=examples or [src.name, src.description],
                   tools=[{"tool": t.name, "preset": link.preset} for link, t in links],
                   followups=list(src.followups))
    out = await create_skill(body, user, db, ctx)
    (await db.get(Skill, out.id)).based_on = src.id
    await db.commit()
    return out


@router.post("/skills/{skill_id}/reembed", response_model=SkillOut)
async def reembed(skill_id: uuid.UUID, user: CurrentUser, db: DbSession, ctx: Context):
    home_id = await _owner_home(db, user)
    skill = await _own(db, skill_id, home_id)
    examples = [c.text for c in await _examples(db, skill.id, home_id, own_only=True)]
    await _save(db, ctx, skill, None, home_id, examples)
    return await _skill_out(db, skill, home_id)


@router.post("/skills/try", response_model=TryOut)
async def try_skills(body: TryIn, user: CurrentUser, db: DbSession, ctx: Context):
    """Which skills a question would find, with their scores. Nothing runs."""
    home_id = await require_home(db, user)
    vector = await ctx.embedder().embed_query(body.question)
    found = await retrieval.search(db, str(home_id), vector)
    tools = []
    if found:
        skill = await retrieval.load_skill(db, home_id=str(home_id), code=found[0]["code"])
        tools = [t["name"] for t in skill["tools"]] if skill else []
    return TryOut(case=retrieval.case_of(found), tools=tools,
                  candidates=[{"code": c["code"], "name": c["name"], "sim": c["sim"],
                               "household": c["own"]} for c in found])


@router.get("/tools", response_model=list[ToolOut])
async def list_tools(user: CurrentUser, db: DbSession):
    await require_home(db, user)
    rows = (await db.execute(select(Tool).where(Tool.enabled, Tool.user_selectable)
                             .order_by(Tool.category, Tool.name))).scalars().all()
    return [ToolOut(name=t.name, label_vi=t.label_vi, label_en=t.label_en,
                    description=t.description, category=t.category, side_effect=t.side_effect,
                    presettable={k: t.parameters.get("properties", {}).get(k, {})
                                 for k in t.presettable}) for t in rows]


@router.get("/memory", response_model=MemoryOut)
async def get_memory(user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    home = await db.get(Home, home_id)
    facts = (await db.execute(select(HomeMemory).where(
        HomeMemory.home_id == home_id,
        (HomeMemory.user_id.is_(None)) | (HomeMemory.user_id == user.id))
        .order_by(HomeMemory.kind, HomeMemory.key))).scalars().all()
    sessions = (await db.execute(select(SessionSummary).where(SessionSummary.home_id == home_id)
                                 .order_by(SessionSummary.ended_at.desc()).limit(50))).scalars()
    return MemoryOut(
        enabled=home.copilot_memory,
        facts=[{"id": f.id, "kind": f.kind, "key": f.key, "value": f.value,
                "confidence": f.confidence, "last_seen_at": f.last_seen_at} for f in facts],
        sessions=[{"conversation_id": s.conversation_id, "started_at": s.started_at,
                   "ended_at": s.ended_at, "turns": s.turns, "summary": s.summary,
                   "topics": s.topics, "skills_used": s.skills_used, "tools_used": s.tools_used,
                   "actions": s.actions, "outcome": s.outcome} for s in sessions])


@router.delete("/memory/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_fact(fact_id: int, user: CurrentUser, db: DbSession):
    home_id = await require_home(db, user)
    fact = await db.get(HomeMemory, fact_id)
    if fact is None or fact.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fact not found")
    await db.delete(fact)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/memory", status_code=status.HTTP_204_NO_CONTENT)
async def forget_all(user: CurrentUser, db: DbSession):
    home_id = await _owner_home(db, user)
    await db.execute(delete(HomeMemory).where(HomeMemory.home_id == home_id))
    await db.execute(delete(SessionSummary).where(SessionSummary.home_id == home_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/memory/enabled", response_model=MemoryOut)
async def switch_memory(body: EnabledIn, user: CurrentUser, db: DbSession):
    home_id = await _owner_home(db, user)
    (await db.get(Home, home_id)).copilot_memory = body.enabled
    await db.commit()
    return await get_memory(user, db)
