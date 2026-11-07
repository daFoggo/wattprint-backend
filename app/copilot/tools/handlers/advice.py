"""Advice tools: read the open suggestions and measured savings, and the eight steps of the
daily_advice pipeline (each reads the earlier steps' output from rc.results)."""

import logging
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select

from ....models import Rule, SavingsMeasure, Suggestion
from ...agents import llm
from ...agents.state import Phrasing
from ...skills import advice, answer_facts, motifs, rules
from .. import db_connector as db
from .. import home_data
from ..registry import RunContext, handler
from .billing import tariff_on

log = logging.getLogger(__name__)


@handler("read_suggestions")
async def read_suggestions(args, rc: RunContext) -> dict:
    async with db.copilot_tx(rc.ctx.copilot(), rc.token) as conn:
        found = await home_data.read_suggestions(conn)
    return {"data": {"suggestions": found}, "facts": answer_facts.advice_facts(found, rc.lang),
            "no_data": not found, "api": {"suggestions": found}}


@handler("get_savings")
async def get_savings(args, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        rows = (await s.execute(
            select(Suggestion.title, SavingsMeasure.baseline_kwh, SavingsMeasure.actual_kwh,
                   SavingsMeasure.method)
            .join(SavingsMeasure, SavingsMeasure.suggestion_id == Suggestion.id)
            .where(Suggestion.home_id == uuid.UUID(rc.home["id"])))).all()
    items = [{"title": r.title, "baseline_kwh": float(r.baseline_kwh),
              "actual_kwh": float(r.actual_kwh),
              "saved_kwh": round(float(r.baseline_kwh - r.actual_kwh), 3), "method": r.method}
             for r in rows]
    return {"data": {"measured": items}, "no_data": not items}


# --- the daily_advice pipeline ---


class KeepArgs(BaseModel):
    keep: int = Field(default=3, ge=1, le=5, description="how many suggestions to keep")


def _home_id(rc: RunContext) -> uuid.UUID:
    return uuid.UUID(rc.home["id"])


@handler("derive_cycles", side_effect="write")
async def derive_cycles(args, rc: RunContext) -> dict:
    lo, hi = motifs.window(rc.today, rc.home["timezone"])
    async with rc.ctx.app()() as s:
        n = await motifs.derive_cycles(s, _home_id(rc), lo, hi)
    return {"data": {"cycles": n}}


@handler("detect_motifs", side_effect="write")
async def detect_motifs(args, rc: RunContext) -> dict:
    tariff = await tariff_on(rc, rc.today)
    async with rc.ctx.app()() as s:
        out = await motifs.detect(s, _home_id(rc), rc.today, rc.home, tariff)
    return {"data": {"instances": sum(out["counts"].values()), "counts": out["counts"],
                     "monthly_kwh": out["monthly_kwh"], "tariff": tariff}}


@handler("evaluate_rules")
async def evaluate_rules(args, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        await rules.ensure_shared(s)
        found = [{"id": str(r.id), "name": r.name, "body": r.body, "kind": r.suggest_kind}
                 for r in (await s.execute(
                     select(Rule).where(Rule.enabled, (Rule.home_id.is_(None))
                                        | (Rule.home_id == _home_id(rc)))
                     .order_by(Rule.home_id.nulls_first(), Rule.name))).scalars()]
    candidates = []
    async with db.copilot_tx(rc.ctx.copilot(), rc.token) as conn:
        names = await home_data.device_names(conn)
        for rule in found:
            body = rules.validate(rule["body"])
            for hit in await rules.evaluate(conn, body, rc.today, rc.home["timezone"]):
                candidates.append({
                    "rule_id": rule["id"], "rule": rule["name"], "kind": rule["kind"],
                    "motif": body.motif, "window_days": body.window_days,
                    "device_id": hit["device_id"], "device": names.get(hit["device_id"]),
                    "instances": hit["instances"],
                })
    return {"data": {"candidates": candidates, "rules": len(found)}}


@handler("price_candidates")
async def price_candidates(args, rc: RunContext) -> dict:
    found = rc.results.get("detect_motifs") or {}
    tariff = found.get("tariff") or await tariff_on(rc, rc.today)
    candidates = (rc.results.get("evaluate_rules") or {}).get("candidates", [])
    priced = [advice.price(c, tariff, found.get("monthly_kwh") or 0.0)
              for c in candidates if tariff.get("tiers")]
    return {"data": {"priced": priced}}


@handler("rank_candidates", KeepArgs)
async def rank_candidates(args: KeepArgs, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        stats = await home_data.feedback_stats(s, _home_id(rc), rc.today)
    priced = (rc.results.get("price_candidates") or {}).get("priced", [])
    return {"data": {"ranked": advice.rank(priced, stats, keep=args.keep)}}


@handler("phrase_suggestions")
async def phrase_suggestions(args, rc: RunContext) -> dict:
    model = rc.ctx.optional_model()
    out = []
    for c in (rc.results.get("rank_candidates") or {}).get("ranked", []):
        facts = {**c["evidence"], "device": c.get("device") or ""}
        title, body = advice.TEMPLATES[c["kind"]]
        if model is not None:
            try:
                p = await llm.structured(model, Phrasing, llm.PHRASE, dict(
                    kind=c["kind"], device=c.get("device"), facts=facts, language="vi"))
                advice.fill_placeholders(p.title, p.body, facts)  # rejects stray numbers
                title, body = p.title, p.body
            except Exception:
                log.info("phrase: using the template for %s", c["kind"])
        title, body = advice.fill_placeholders(title, body, facts)
        out.append({**c, "title": title, "body": body})
    return {"data": {"phrased": out}}


@handler("store_suggestions", side_effect="write")
async def store_suggestions(args, rc: RunContext) -> dict:
    ids, stored = [], []
    async with rc.ctx.app()() as s:
        for c in (rc.results.get("phrase_suggestions") or {}).get("phrased", []):
            row = Suggestion(
                home_id=_home_id(rc),
                device_id=uuid.UUID(c["device_id"]) if c.get("device_id") else None,
                kind=c["kind"], title=c["title"], body=c["body"],
                expected_kwh=round(c["saving_kwh"], 3), expected_amount=c["saving_vnd"],
                status="proposed", rule_id=uuid.UUID(c["rule_id"]),
                motif_instance_id=uuid.UUID(c["instance_id"]),
                evidence={**c["evidence"], "p_accept": c["p_accept"], "rule": c["rule"]},
            )
            s.add(row)
            await s.flush()
            ids.append(str(row.id))
            stored.append({"id": str(row.id), "kind": c["kind"], "title": c["title"],
                           "body": c["body"], "expected_amount": float(c["saving_vnd"])})
        await s.commit()
    return {"data": {"stored": ids, "suggestions": stored},
            "facts": answer_facts.advice_facts(stored, rc.lang), "api": {"suggestions": stored}}


@handler("measure_savings", side_effect="write")
async def measure_savings(args, rc: RunContext) -> dict:
    async with rc.ctx.app()() as s:
        done = await home_data.measure_savings(s, _home_id(rc), rc.today, rc.home["timezone"])
    return {"data": {"measured": done}}
