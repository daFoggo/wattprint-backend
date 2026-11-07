"""Run a scheduled or event skill of the Copilot graph (replaces copilot_advise).

    python -m app.cli.copilot_run --skill daily_advice [--home ID] [--today YYYY-MM-DD] [--no-llm]
    python -m app.cli.copilot_run --sessions [--idle-minutes 30]

`--skill`: the skill's pipeline for one home or every home with a main meter (cron, 02:00).
`--sessions`: the session_closed sweep (cron, every 10 min): summarise each conversation quiet
for --idle-minutes whose messages are newer than its summary, for homes with memory on.
"""

import argparse
import asyncio
import datetime as dt
import sys
import uuid

from sqlalchemy import text

from ..copilot.agents.base_agent import CopilotContext
from ..copilot.agents.router import copilot_graph

QUIET = text("""
SELECT c.id::text AS conversation_id, c.home_id::text AS home_id
FROM copilot.conversation c JOIN core.home h ON h.id = c.home_id AND h.copilot_memory
JOIN LATERAL (SELECT max(created_at) AS last FROM copilot.message m
              WHERE m.conversation_id = c.id) m ON true
LEFT JOIN copilot.session_summary s ON s.conversation_id = c.id
WHERE m.last < now() - make_interval(mins => :idle)
  AND (s.covers_until IS NULL OR m.last > s.covers_until)
""")


async def run_skill(home_id: uuid.UUID, skill_code: str, ctx: CopilotContext,
                    conversation_id: str | None = None) -> dict:
    """One home's run of a schedule (or event) skill; tests call it directly."""
    trigger = "event" if conversation_id else "schedule"
    return await copilot_graph.ainvoke({"trigger": trigger, "home_id": str(home_id),
                                        "skill_code": skill_code,
                                        "conversation_id": conversation_id}, context=ctx)


async def quiet_sessions(ctx: CopilotContext, idle_minutes: int = 30) -> list[dict]:
    async with ctx.app()() as s:
        return [dict(r._mapping) for r in await s.execute(QUIET, {"idle": idle_minutes})]


def summary_line(state: dict) -> str:
    return ", ".join(f"{r['tool']}: {'ok' if r['ok'] else r.get('error')}"
                     for r in state.get("results", [])) or "nothing ran"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.cli.copilot_run", description=__doc__)
    p.add_argument("--skill", help="a schedule skill code, e.g. daily_advice")
    p.add_argument("--sessions", action="store_true", help="summarise quiet sessions")
    p.add_argument("--home", type=uuid.UUID, help="one home (default: every home with data)")
    p.add_argument("--today", type=dt.date.fromisoformat, help="pin the date (default: today)")
    p.add_argument("--idle-minutes", type=int, default=30)
    p.add_argument("--no-llm", action="store_true", help="template text only")
    return p


async def main(argv: list[str] | None = None, ctx: CopilotContext | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    ctx = ctx or CopilotContext(chat_model=False if args.no_llm else None, today=args.today)
    if args.sessions:
        jobs = [(r["home_id"], "session_summary", r["conversation_id"])
                for r in await quiet_sessions(ctx, args.idle_minutes)]
    elif args.skill:
        async with ctx.app()() as s:
            homes = [str(args.home)] if args.home else list((await s.execute(text(
                "SELECT DISTINCT home_id::text FROM energy.series WHERE kind = 'main'"))).scalars())
        jobs = [(h, args.skill, None) for h in homes]
    else:
        parser.error("give --skill or --sessions")
    failed = 0
    for home_id, code, conv in jobs:
        try:
            state = await run_skill(uuid.UUID(home_id), code, ctx, conv)
        except Exception as exc:  # one home's failure must not stop the others
            failed += 1
            print(f"{home_id} {code}: failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        print(f"{home_id} {code}{' ' + conv if conv else ''}: {summary_line(state)}")
    return 1 if failed else 0


async def _cli() -> int:
    from ..database import engine

    try:
        return await main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_cli()))
