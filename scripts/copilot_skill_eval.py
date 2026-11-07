"""Ask the skill/tool chat cases with the REAL model and bge-m3 and score them (spec section 9).

    uv run python scripts/copilot_skill_eval.py --setup            # scratch DB from the dump
    uv run python scripts/copilot_skill_eval.py --dsn DSN [--only S01,M02]

--setup builds a database like the tests' demo home (REFIT House 2, 29 Oct .. 4 Nov 2026), migrated
to head, with the catalog synced and embedded by bge-m3, and prints its DSN. The run asks every case
of docs/copilot-tests/skill-tool-cases.yaml through the Copilot graph (built queries run on the
read-only login wattprint_copilot_ro), reads back tool_call, alert, suggestion and memory rows, and
writes docs/copilot-tests/skill-tool-results.{json,md}. Needs OPENROUTER_* in .env.
"""

import argparse
import asyncio
import datetime as dt
import json
import statistics
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.cli.copilot_run import run_skill  # noqa: E402
from app.copilot.agents.base_agent import CopilotContext  # noqa: E402
from app.copilot.agents.router import copilot_graph  # noqa: E402
from app.copilot.skills.catalog_sync import replace_chunks, sync  # noqa: E402
from app.copilot.skills.chunker import no_tone, skill_chunks  # noqa: E402
from app.copilot.skills.grounding import numbers, readings, ungrounded  # noqa: E402
from app.copilot.tools.embedder import default_embedder  # noqa: E402
from app.copilot.tools.handlers.billing import price_tiers  # noqa: E402
from app.copilot.utils.helpers import detect_lang  # noqa: E402
from app.models import Skill, SkillSetting, SkillTool  # noqa: E402
from app.routers.copilot import ask_out  # noqa: E402

TODAY = dt.date(2026, 11, 5)
CASES = ROOT / "docs" / "copilot-tests" / "skill-tool-cases.yaml"
OUT = ROOT / "docs" / "copilot-tests" / "skill-tool-results"
EMAIL, OTHER_EMAIL = "owner@example.com", "other@example.com"


async def setup() -> str:
    from app.cli.migrate_legacy import make_plan, migrate, read_legacy
    from app.schemas.user import UserCreate
    from app.services.aggregates import backfill_aggregates
    from app.services.auth import register_user
    from app.services.disaggregation import local_day_start
    from tests.db.conftest import DUMP, _create_migrated_db

    dsn, _ = await _create_migrated_db()
    folder = Path(tempfile.mkdtemp())
    with tarfile.open(DUMP) as tar:
        tar.extractall(folder, filter="data")
    engine = create_async_engine(dsn)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as s:
        await register_user(s, UserCreate(email=EMAIL, password="demo-password-123",
                                          full_name="Anh Demo"))
        legacy = read_legacy(folder)
        plan = make_plan(legacy, TODAY - dt.timedelta(days=1), TODAY)
        await migrate(s, legacy, plan, 2, EMAIL)
        other = await register_user(s, UserCreate(email=OTHER_EMAIL, password="other-pass-123",
                                                  full_name="Nhà khác"))
        home = await s.scalar(text("INSERT INTO core.home (name) VALUES ('Nhà khác') RETURNING id"))
        await s.execute(text("INSERT INTO core.home_member (home_id, user_id, role) "
                             "VALUES (:h, :u, 'owner')"), {"h": home, "u": other.id})
        await s.commit()
    auto = create_async_engine(dsn, isolation_level="AUTOCOMMIT")
    async with auto.connect() as c:
        await backfill_aggregates(c, local_day_start(plan.first_target),
                                  local_day_start(plan.last_target) + dt.timedelta(days=1))
    await auto.dispose()
    t0 = time.perf_counter()
    async with sessions() as s:
        print("sync", await sync(s, default_embedder()), f"{time.perf_counter() - t0:.0f} s")
    await engine.dispose()
    return dsn


class Run:
    def __init__(self, dsn: str):
        url = make_url(dsn)
        self.engine = create_async_engine(dsn)
        self.ro = create_async_engine(url.set(username="wattprint_copilot_ro", password="copilot"))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.ctx = CopilotContext(app_sessions=self.sessions,
                                  copilot_sessions=async_sessionmaker(self.ro), today=TODAY)

    async def ids(self):
        async with self.sessions() as s:
            self.users = dict((await s.execute(text("SELECT email, id::text FROM users"))).all())
            self.homes = dict((await s.execute(text(
                "SELECT u.email, m.home_id::text FROM users u JOIN core.home_member m "
                "ON m.user_id = u.id"))).all())
            self.devices = dict((await s.execute(text(
                "SELECT name, id::text FROM core.device WHERE home_id = :h"),
                {"h": uuid.UUID(self.homes[EMAIL])})).all())

    async def reset(self, keep_memory: bool):
        sql = ["DELETE FROM copilot.skill WHERE home_id IS NOT NULL",
               "DELETE FROM copilot.skill_setting", "DELETE FROM insight.alert",
               "UPDATE core.home SET copilot_memory = true"]
        if not keep_memory:
            sql += ["DELETE FROM copilot.home_memory", "DELETE FROM copilot.session_summary"]
        async with self.sessions() as s:
            for q in sql:
                await s.execute(text(q))
            await s.commit()

    async def household_skill(self, spec: dict, email: str):
        home = uuid.UUID(self.homes[email])
        async with self.sessions() as s:
            skill = Skill(home_id=home, code="kitchen_report", name=spec["name"],
                          description=spec["description"])
            s.add(skill)
            await s.flush()
            for i, t in enumerate(spec["tools"]):
                tool = await s.scalar(text("SELECT id FROM copilot.tool WHERE name = :n"),
                                      {"n": t["tool"]})
                preset = dict(t.get("preset", {}))
                if "devices" in preset:
                    preset["device_ids"] = [self.devices[n] for n in preset.pop("devices")]
                s.add(SkillTool(skill_id=skill.id, tool_id=tool, ord=i, preset=preset))
            skill.embed_status = await replace_chunks(
                s, self.ctx.embedder(),
                skill_chunks(skill.name, skill.description, spec["examples"]),
                skill_id=skill.id, home_id=home)
            await s.commit()

    async def disable(self, code: str):
        async with self.sessions() as s:
            skill = await s.scalar(text("SELECT id FROM copilot.skill WHERE home_id IS NULL "
                                        "AND code = :c"), {"c": code})
            s.add(SkillSetting(home_id=uuid.UUID(self.homes[EMAIL]), skill_id=skill,
                               enabled=False))
            await s.commit()

    async def ask(self, question: str, conv: str | None, email: str):
        t0 = time.perf_counter()
        state = await copilot_graph.ainvoke(
            {"trigger": "chat", "question": question, "user_id": self.users[email],
             "conversation_id": conv}, context=self.ctx)
        ms = round((time.perf_counter() - t0) * 1000)
        return ask_out(state).model_dump(mode="json"), state, ms

    async def summarize(self, conv: str, email: str):
        on = await self.scalar("SELECT copilot_memory FROM core.home WHERE id = :h",
                               h=uuid.UUID(self.homes[email]))
        if on:  # the session_closed sweep skips homes with memory off
            return await run_skill(uuid.UUID(self.homes[email]), "session_summary", self.ctx, conv)
        return {}

    async def scalar(self, sql: str, **params):
        async with self.sessions() as s:
            return await s.scalar(text(sql), params)


DEFAULTS = {"measure": "energy", "grain": "none", "group_by": "none", "compare_to": "none"}


def _norm(v):
    if isinstance(v, list):
        return sorted(map(str, v))
    if isinstance(v, int | float) and not isinstance(v, bool):
        return str(float(v))  # 200 and 200.0 are the same threshold
    return str(v)


def args_match(expected: dict, got: dict, devices: dict) -> bool:
    for k, v in expected.items():
        if k == "devices":
            ids = sorted(devices[n] for n in v)
            if sorted(got.get("device_ids") or []) != ids and not got.get("device_type_codes"):
                return False
        elif k == "target":
            whole = not got.get("device_ids") and not got.get("device_type_codes")
            if (v == "whole_home") != whole:
                return False
        elif _norm(got.get(k) if got.get(k) is not None else DEFAULTS.get(k)) != _norm(v):
            return False
    return True


def found_number(value: float, tol: float, texts: list[str]) -> bool:
    vals = {r for t in texts for tok in numbers(t) for r in readings(tok)}
    return any(abs(v - value) <= tol for v in vals)


ORACLE_DEVICE_DAY = """
SELECT round((sum(x.energy_wh) / 1000)::numeric, 2)::float
FROM energy.device_estimate_1d x JOIN energy.series s USING (series_id)
JOIN core.device d ON d.id = s.device_id
WHERE d.name = :name AND x.bucket >= :lo AND x.bucket < :hi
"""


async def oracle(run: Run, spec: str) -> float | None:
    if spec.startswith("kWh of the highest day"):
        return await run.scalar(
            "SELECT round(max(e)::numeric, 2)::float FROM (SELECT sum(energy_wh) / 1000 e "
            "FROM energy.reading_1d r JOIN energy.series s USING (series_id) WHERE s.kind = "
            "'main' AND r.bucket >= '2026-10-31 17:00+00' AND r.bucket < '2026-11-04 17:00+00' "
            "GROUP BY r.bucket) d")
    if spec.startswith("Washing Machine kWh on 2026-11-03"):
        return await run.scalar(ORACLE_DEVICE_DAY, name="Washing Machine",
                                lo=dt.datetime(2026, 11, 2, 17, tzinfo=dt.UTC),
                                hi=dt.datetime(2026, 11, 3, 17, tzinfo=dt.UTC))
    if spec.startswith("Microwave kWh"):
        return await run.scalar(ORACLE_DEVICE_DAY, name="Microwave",
                                lo=dt.datetime(2026, 10, 28, 17, tzinfo=dt.UTC),
                                hi=dt.datetime(2026, 11, 4, 17, tzinfo=dt.UTC))
    if spec.startswith(("tiered price of 601.6", "(forecast 601.6")):
        async with run.sessions() as s:
            rows = (await s.execute(text(
                "SELECT t.tier_no, t.from_kwh::float, t.to_kwh::float, t.price_per_kwh::float, "
                "v.vat_rate::float FROM billing.tariff_tier t JOIN billing.tariff_version v "
                "ON v.id = t.version_id JOIN core.home h ON h.tariff_plan_code = v.plan_code "
                "WHERE h.id = :h AND v.valid_from <= '2026-11-01' AND (v.valid_to IS NULL OR "
                "v.valid_to >= '2026-11-01') ORDER BY t.tier_no"),
                {"h": uuid.UUID(run.homes[EMAIL])})).all()
        tiers = [{"tier_no": r[0], "from_kwh": r[1], "to_kwh": r[2], "price": r[3]} for r in rows]
        kwh = round(66.92 + 26 * 143.96 / 7, 2)
        if spec.startswith("tiered"):
            return price_tiers(kwh, {"tiers": tiers, "vat_rate": rows[0][4]})["amount"]
        tier = next(t for t in tiers if t["to_kwh"] is None or kwh <= t["to_kwh"])
        return round((kwh - tier["from_kwh"]) / 26, 2)
    if spec.startswith("expected_amount of the suggestions"):
        return await run.scalar("SELECT max(expected_amount)::float FROM copilot.suggestion "
                                "WHERE status = 'proposed'")
    return None


async def db_check(run: Run, key: str, want, extra: dict) -> bool:
    home = uuid.UUID(run.homes[EMAIL])
    if key == "insight.alert rows for the home":
        return await run.scalar("SELECT count(*) FROM insight.alert WHERE home_id = :h",
                                h=home) == want
    if key == "copilot.session_summary rows for the home":
        return await run.scalar("SELECT count(*) FROM copilot.session_summary "
                                "WHERE home_id = :h", h=home) == want
    if key == "copilot.rule still exists":
        return bool(await run.scalar("SELECT to_regclass('copilot.rule') IS NOT NULL"))
    if key == "home_memory preference.lang = en with evidence":
        return await run.scalar("SELECT count(*) FROM copilot.home_memory WHERE key = "
                                "'preference.lang' AND value->>'lang' = 'en' AND "
                                "cardinality(evidence) > 0") >= want
    if key == "copilot.suggestion rows created in this run":
        n = await run.scalar("SELECT count(*) FROM copilot.suggestion WHERE created_at > "
                             "now() - interval '3 minutes'")
        return 1 <= n <= 3
    if key == "tool_call rows for the run":
        return await run.scalar("SELECT count(*) FROM copilot.tool_call WHERE home_id = :h AND "
                                "message_id IS NULL AND created_at > now() - interval '3 minutes'",
                                h=home) >= want
    conv = extra.get("conv")
    async with run.sessions() as s:
        row = (await s.execute(text("SELECT * FROM copilot.session_summary WHERE "
                                    "conversation_id = :c"), {"c": uuid.UUID(conv)})).first() \
            if conv else None
        calls = [json.dumps(r[0], ensure_ascii=False) for r in (await s.execute(text(
            "SELECT t.input FROM copilot.tool_call t JOIN copilot.message m ON m.id = t.message_id "
            "WHERE m.conversation_id = :c"), {"c": uuid.UUID(conv)})).all()] if conv else []
    if key == "copilot.session_summary row for the session":
        return (1 if row else 0) == want
    if row is None:
        return False
    return {
        "skills_used": lambda: list(row.skills_used) == want,
        "tools_used contains": lambda: set(want) <= {t["tool"] for t in row.tools_used},
        "topics contains one of": lambda: any(no_tone(w) in no_tone(" ".join(row.topics))
                                              for w in want),
        "turns": lambda: row.turns == want,
        "numbers in summary all appear in the session's tool results":
            lambda: ungrounded(row.summary, calls) == [],
    }.get(key, lambda: False)()


async def score(run: Run, case: dict, out: dict, state: dict, ms: int, extra: dict) -> dict:
    exp, checks = case.get("expect", {}), {}
    ret, r = exp.get("retrieval", {}), out.get("retrieval") or {}
    cands = [c["code"] for c in r.get("candidates", [])]
    chosen = (out.get("skill") or {}).get("code")
    rank = cands.index(ret["skill"]) + 1 if ret.get("skill") in cands else None
    if ret.get("skill"):
        checks["skill"] = chosen == ret["skill"]
        if r.get("case") != "given":
            checks["rank"] = rank is not None and rank <= ret.get("rank_max", 1)
    if ret.get("decision") and ret["decision"] != "given":
        checks["case"] = r.get("case") == ret["decision"]
    if ret.get("decision_in"):
        checks["case"] = r.get("case") in ret["decision_in"]
    if ret.get("absent"):
        checks["absent"] = not set(ret["absent"]) & set(cands) and chosen not in ret["absent"]
    tools, got = exp.get("tools", {}), out.get("tools", [])
    expected = tools.get("calls", [])
    matched = [any(g["tool"] == e["name"] and args_match(e.get("args", {}), g["args"],
                                                          run.devices) for g in got)
               for e in expected]
    if expected:
        checks["args"] = all(matched)
        if tools.get("ordered"):
            names = [e["name"] for e in expected]
            checks["order"] = [g["tool"] for g in got][:len(names)] == names
        for e in expected:
            if "executed" in e:
                ran = [g for g in got if g["tool"] == e["name"]]
                checks["write_safety"] = bool(ran) and (ran[0]["ok"] is not None) == e["executed"]
    if tools.get("forbid"):
        forbid = tools["forbid"]
        checks["forbid"] = not got if "*" in forbid else not {g["tool"] for g in got} & set(forbid)
    if "llm_rounds" in tools:
        checks["llm_rounds"] = (state.get("rounds") or 0) == tools["llm_rounds"]
    if tools.get("no_arg_named"):
        checks["no_sql_arg"] = all(not set(tools["no_arg_named"]) & set(g["args"]) for g in got)
    ans = exp.get("answer", {})
    texts = [out.get("answer", ""), json.dumps(out.get("facts", []), ensure_ascii=False)]
    for n in ans.get("numbers", []):
        value = n.get("value") if n.get("value") is not None else await oracle(run, n["oracle"])
        checks[f"number {value}"] = value is not None and found_number(value, n["tol"], texts)
    for alternatives in ans.get("must", []):
        checks[f"says {alternatives[0]}"] = any(no_tone(a) in no_tone(out.get("answer", ""))
                                                for a in alternatives)
    if ans.get("lang"):
        checks["lang"] = detect_lang(out.get("answer", "")) == ans["lang"]
    if ans.get("clarification"):
        c = out.get("clarification") or {}
        checks["clarification"] = (c.get("reason") == ans["clarification"]["reason"] and
                                   {o["label"] for o in c.get("options", [])}
                                   == set(ans["clarification"]["options"]))
    if ans.get("confirm_card"):
        checks["confirm_card"] = ((out.get("confirm") or {}).get("tool")
                                  == ans["confirm_card"]["tool"])
    if ans.get("reply") == "none":
        checks["no_reply"] = not out.get("answer")
    if rw := exp.get("rewrite"):
        call = next((g for g in got if g["tool"] == "query_usage"), None)
        ok = r.get("rewrite") == rw["method"] if rw.get("method") else True
        if rw.get("devices"):
            ok = ok and call is not None and args_match({"devices": rw["devices"]}, call["args"],
                                                        run.devices)
        if rw.get("start"):
            ok = ok and call is not None and call["args"].get("start") == str(rw["start"])
        checks["rewrite"] = ok
    mem, recalled = exp.get("long_memory", {}), out.get("memory", [])
    if "sessions_min" in mem:
        checks["memory_recalled"] = len(recalled) >= mem["sessions_min"]
    if "sessions_max" in mem:
        checks["memory_isolated"] = len(recalled) <= mem["sessions_max"]
    if "facts_contains" in mem:
        checks["facts"] = await run.scalar("SELECT count(*) FROM copilot.home_memory "
                                           "WHERE key = ANY(:k)", k=mem["facts_contains"]) > 0
    if exp.get("short_memory"):
        checks["short_memory"] = r.get("rewrite") == "rule"
    for key, want in (exp.get("db") or {}).items():
        checks[f"db: {key}"] = await db_check(run, key, want, extra)
    checks["latency"] = ms <= case.get("budget_ms", 3500)
    flags = state.get("flags") or []
    return {
        "id": case["id"], "question": case.get("question"), "expected_skill": ret.get("skill"),
        "skill": chosen, "rank": rank, "case": r.get("case"),
        "candidates": r.get("candidates", [])[:3], "standalone": r.get("standalone"),
        "rewrite": r.get("rewrite"), "expected_tools": [e["name"] for e in expected],
        "tools": [{"tool": g["tool"], "args": g["args"], "ok": g["ok"], "ms": g["ms"]}
                  for g in got],
        "answer": out.get("answer"), "facts": out.get("facts"), "latency_ms": ms,
        "timings": out.get("timings", []), "flags": flags,
        "grounded": not any(f.startswith("ungrounded") for f in flags),
        "checks": checks, "pass": all(v for k, v in checks.items() if k != "case"),
        "tool_precision": (sum(any(g["tool"] == e["name"] for e in expected) for g in got)
                           / len(got)) if got else (1.0 if not expected else 0.0),
        "tool_recall": (sum(matched) / len(expected)) if expected else 1.0,
    }


async def run_case(run: Run, case: dict) -> dict:
    email = OTHER_EMAIL if case.get("home") == "other" else EMAIL
    await run.reset(keep_memory=case["id"].startswith("M0") and case["id"] != "M02")
    fx = case.get("fixture") or {}
    if fx.get("add_household_skill"):
        await run.household_skill(run.cases["household_skills"][fx["add_household_skill"]],
                                  OTHER_EMAIL if fx.get("to_home") == "other" else EMAIL)
    if fx.get("disable_system_skill"):
        await run.disable(fx["disable_system_skill"])
    if fx.get("home_memory_enabled") is False:
        async with run.sessions() as s:
            await s.execute(text("UPDATE core.home SET copilot_memory = false WHERE id = :h"),
                            {"h": uuid.UUID(run.homes[EMAIL])})
            await s.commit()
    if fx.get("clear_suggestions"):
        async with run.sessions() as s:
            for q in ("DELETE FROM copilot.savings_measure",
                      "DELETE FROM copilot.suggestion_feedback",
                      "DELETE FROM copilot.suggestion", "DELETE FROM insight.motif_instance"):
                await s.execute(text(q))
            await s.commit()
    if fx.get("run_advice"):
        await run_skill(uuid.UUID(run.homes[EMAIL]), "daily_advice", run.ctx)
    extra, conv = {}, None
    if case.get("session"):
        for q in case["session"]:
            out, _, _ = await run.ask(q, conv, email)
            conv = out["conversation_id"]
        extra["conv"] = conv
        if case.get("then_event") or case.get("trigger") == "event":
            extra["event_state"] = await run.summarize(conv, email)
        conv = None
    for q in case.get("turns", []):
        out, _, _ = await run.ask(q, conv, email)
        conv = out["conversation_id"]
    if case.get("trigger") == "schedule":
        t0 = time.perf_counter()
        state = await run_skill(uuid.UUID(run.homes[email]), case["skill_code"], run.ctx)
        ms = round((time.perf_counter() - t0) * 1000)
        out = {"answer": state.get("answer", ""), "steps": state.get("steps", []),
               "tools": [{"tool": x["tool"], "args": x.get("args", {}), "ok": x["ok"],
                          "ms": x["ms"]} for x in state.get("results", [])],
               "retrieval": {"case": "given"}, "skill": {"code": case["skill_code"]},
               "timings": state.get("timings", [])}
    elif case.get("trigger") == "event":
        state = extra.get("event_state") or {}
        out = {"answer": "", "retrieval": {"case": "given"}, "skill": {"code": "session_summary"},
               "tools": [{"tool": x["tool"], "args": x.get("args", {}), "ok": x["ok"],
                          "ms": x["ms"]} for x in state.get("results", [])]}
        ms = sum(t["ms"] for t in state.get("timings", []))
    else:
        out, state, ms = await run.ask(case["question"], conv, email)
    return await score(run, case, out, state, ms, extra)


def metrics(rows: list[dict]) -> dict:
    with_skill = [r for r in rows if r["expected_skill"] and r["case"] != "given"]
    ranks = [r["rank"] for r in with_skill]
    chat = sorted(r["latency_ms"] for r in rows if r["latency_ms"] and r["case"] != "given")

    def share(xs):
        xs = list(xs)
        return round(sum(xs) / len(xs), 3) if xs else None

    def check(name, ids=None):
        return share(r["checks"][name] for r in rows
                     if name in r["checks"] and (ids is None or r["id"] in ids))

    return {
        "cases": len(rows), "passed": sum(r["pass"] for r in rows),
        "hit@1": share(x == 1 for x in ranks), "hit@3": share(bool(x and x <= 3) for x in ranks),
        "mrr": share(1 / x if x else 0 for x in ranks), "case_accuracy": check("case"),
        "skill_precision": share(r["skill"] == r["expected_skill"] for r in with_skill
                                 if r["skill"]),
        "out_of_scope_precision": share(r["skill"] is None for r in rows if r["id"] == "S10"),
        "tool_precision": share(r["tool_precision"] for r in rows),
        "tool_recall": share(r["tool_recall"] for r in rows),
        "argument_accuracy": check("args"), "write_safety": check("write_safety"),
        "home_isolation": share([*(r["checks"]["absent"] for r in rows if r["id"] == "S14"
                                   and "absent" in r["checks"]),
                                 *(r["checks"]["memory_isolated"] for r in rows
                                   if "memory_isolated" in r["checks"])]),
        "answer_numbers": share(v for r in rows for k, v in r["checks"].items()
                                if k.startswith("number")),
        "grounding": share(r["grounded"] for r in rows), "rewrite_accuracy": check("rewrite"),
        "latency_p50_ms": statistics.median(chat) if chat else None,
        "latency_p95_ms": chat[min(len(chat) - 1, round(0.95 * (len(chat) - 1)))] if chat else None,
    }


def write(rows: list[dict], m: dict) -> None:
    OUT.with_suffix(".json").write_text(json.dumps({"metrics": m, "cases": rows},
                                                   ensure_ascii=False, indent=1, default=str))
    lines = ["# Skill/tool chat cases: results", "",
             f"Run {dt.datetime.now():%Y-%m-%d %H:%M} · real model and bge-m3 on the demo home "
             "(today pinned to 2026-11-05) · cases: [skill-tool-cases.yaml](skill-tool-cases.yaml)",
             "", "## Metrics", "", "| Metric | Value |", "| --- | --- |",
             *(f"| {k} | {v} |" for k, v in m.items()), "", "## Cases", "",
             "| # | Question | Expected skill → got (rank, case) | Expected tools → got | "
             "Latency | Answer | Pass |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        mark = {False: " ✗", None: " ⏸"}
        got = ", ".join(f"{t['tool']}{mark.get(t['ok'], '')}" for t in r["tools"]) or "—"
        fails = ", ".join(k for k, v in r["checks"].items() if not v)
        answer = (r["answer"] or "—").replace("|", "/").replace("\n", " ")[:160]
        lines.append(f"| {r['id']} | {r['question'] or '(no question)'} | "
                     f"{r['expected_skill'] or '—'} → {r['skill'] or '—'} ({r['rank']}, "
                     f"{r['case']}) | {', '.join(r['expected_tools']) or '—'} → {got} | "
                     f"{r['latency_ms']} ms | {answer} | "
                     f"{'PASS' if r['pass'] else 'FAIL: ' + fails} |")
    OUT.with_suffix(".md").write_text("\n".join(lines) + "\n")


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--setup", action="store_true")
    p.add_argument("--dsn")
    p.add_argument("--only")
    args = p.parse_args()
    if args.setup:
        print(await setup())
        return 0
    run = Run(args.dsn)
    run.cases = yaml.safe_load(CASES.read_text())
    await run.ids()
    await run.reset(keep_memory=False)
    await run.ctx.embedder().embed_query("warm up")  # a server loads bge-m3 once, not per question
    only = set(args.only.split(",")) if args.only else None
    rows = []
    for case in run.cases["cases"]:
        if only and case["id"] not in only:
            continue
        try:
            row = await run_case(run, case)
        except Exception as exc:
            row = {"id": case["id"], "question": case.get("question"),
                   "expected_skill": case.get("expect", {}).get("retrieval", {}).get("skill"),
                   "skill": None, "rank": None, "case": None, "tools": [], "expected_tools": [],
                   "answer": f"ERROR {type(exc).__name__}: {exc}"[:300], "latency_ms": None,
                   "checks": {"ran": False}, "pass": False, "grounded": True, "flags": [],
                   "tool_precision": 0.0, "tool_recall": 0.0}
        print(f"{row['id']}: {'PASS' if row['pass'] else 'FAIL'} "
              f"{[k for k, v in row['checks'].items() if not v]} {row['latency_ms']} ms",
              flush=True)
        rows.append(row)
        write(rows, metrics(rows))  # after every case: a cut-off run keeps what it did
    m = metrics(rows)
    print(json.dumps(m, indent=1))
    write(rows, m)
    await run.engine.dispose()
    await run.ro.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
