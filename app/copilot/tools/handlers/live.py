"""What runs now (NILM), the household's alert watches, and the knowledge documents."""

import datetime as dt
import uuid
from datetime import UTC
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select, text

from ....models import Alert
from ....services.disaggregation import latest
from ...agents.state import Fact
from ..registry import RunContext, handler

ON_W = 20  # an appliance estimate above this is "on"


class MinutesArgs(BaseModel):
    minutes: int = Field(default=15, ge=1, le=120, description="how far back counts as now")


@handler("nilm_latest", MinutesArgs)
async def nilm_latest(args: MinutesArgs, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        out = await latest(s, uuid.UUID(rc.home["id"]), args.minutes)
    if not out.points:
        return {"data": {"recent": False, "latest_ts": None}, "no_data": True}
    last = out.points[-1]
    age = (dt.datetime.now(UTC) - last.ts).total_seconds() / 60
    on = {k: v for k, v in (last.appliances_w or {}).items() if v and v > ON_W}
    data = {"latest_ts": last.ts.isoformat(), "minutes_ago": round(age),
            "recent": age <= args.minutes, "aggregate_w": last.aggregate_w, "on": on}
    vi = rc.lang == "vi"
    facts = [Fact(k="Dữ liệu mới nhất" if vi else "Latest data", v=f"{last.ts:%d/%m %H:%M}")]
    if data["recent"]:
        facts.append(Fact(k="Công suất" if vi else "Power", v=f"{last.aggregate_w:.0f} W"))
        facts += [Fact(k=k, v=f"{v:.0f} W") for k, v in on.items()]
    return {"data": data, "facts": facts, "no_data": not data["recent"]}


@handler("list_alerts")
async def list_alerts(args, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        rows = (await s.execute(select(Alert).where(Alert.home_id == uuid.UUID(rc.home["id"]))
                                .order_by(Alert.ts.desc()).limit(20))).scalars().all()
    items = [{"id": str(a.id), "kind": a.kind, "status": a.status, "ts": a.ts.isoformat(),
              **a.payload} for a in rows]
    return {"data": {"alerts": items}, "no_data": not items}


class AlertArgs(BaseModel):
    measure: Literal["average_power", "peak_power"] = "average_power"
    threshold_w: float = Field(gt=0, le=50000, description="alert when power goes above this")
    start_hour: int = Field(default=0, ge=0, le=23, description="window start, local hour")
    end_hour: int = Field(default=24, ge=1, le=24, description="window end, local hour")
    device_id: str | None = Field(default=None, description="a device of the home from the "
                                  "linked terms; empty = the whole home")


@handler("create_alert", AlertArgs, side_effect="write")
async def create_alert(args: AlertArgs, rc: RunContext) -> dict:
    """A watch row in insight.alert (kind 'watch'). ponytail: nothing fires it yet; a check in
    the daily_advice pipeline is the place when alerts must notify."""
    if args.device_id and args.device_id not in rc.home.get("devices", {}):
        return {"ok": False, "error": "device_id is not a device of this home"}
    async with rc.ctx.app()() as s:
        row = Alert(home_id=uuid.UUID(rc.home["id"]), kind="watch", severity="info",
                    ts=dt.datetime.now(UTC),
                    device_id=uuid.UUID(args.device_id) if args.device_id else None,
                    payload=args.model_dump(mode="json"))
        s.add(row)
        await s.commit()
    vi = rc.lang == "vi"
    window = f"{args.start_hour:02d}:00–{args.end_hour:02d}:00"
    return {"data": {"alert_id": str(row.id), "created": True, **args.model_dump(mode="json")},
            "facts": [Fact(k="Cảnh báo" if vi else "Alert",
                           v=f"> {args.threshold_w:.0f} W · {window}")]}


class KnowledgeArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300, description="what to look up")
    top_k: int = Field(default=3, ge=1, le=5)


@handler("search_knowledge", KnowledgeArgs)
async def search_knowledge(args: KnowledgeArgs, rc: RunContext) -> dict:
    vector = await rc.ctx.embedder().embed_query(args.query)
    async with rc.ctx.app()() as s:
        rows = (await s.execute(text(
            "SELECT d.title, c.body, 1 - (c.embedding <=> CAST(:v AS vector)) AS sim "
            "FROM knowledge.chunk c JOIN knowledge.document d ON d.id = c.document_id "
            "ORDER BY c.embedding <=> CAST(:v AS vector) LIMIT :k"),
            {"v": str(vector), "k": args.top_k})).all()
    passages = [{"title": r.title, "text": r.body, "sim": round(float(r.sim), 3)}
                for r in rows if r.sim >= 0.5]
    return {"data": {"passages": passages}, "no_data": not passages}
