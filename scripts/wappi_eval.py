"""Score Wappi on realistic scenarios: checks that need no model, plus three blind judges.

Calls the real models (Wappi, then three judges per answer) and leaves no conversation or alert.

    docker compose exec -T api python -m scripts.wappi_eval "REFIT House 2" --split tune \
        --out docs/eval/baseline.json
"""

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.copilot.services import chat, tools
from app.modules.home.api import Home, HomeMember
from scripts.eval_wappi import ask, truth
from scripts.wappi_judges import CRITERIA, judge_all
from scripts.wappi_scenarios import SCENARIOS, evaluate
from scripts.wappi_speak import speak_lint

EVIDENCE_CHARS = 4000  # what the judges read of the tools' results
EVIDENCE: list[tuple[str, dict, Any]] = []


def record() -> None:
    """Keep what each tool returned for the answer being judged (the model saw the same data)."""
    original = chat.run_tool

    async def recording(ctx, name, args):
        result = await original(ctx, name, args)
        EVIDENCE.append((name, args, result[0].data))
        return result

    chat.run_tool = recording


def evidence_text() -> str:
    lines = [
        f"{name}({json.dumps(args, ensure_ascii=False)}): "
        + json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
        for name, args, data in EVIDENCE
    ]
    return "\n".join(lines)[:EVIDENCE_CHARS]


def as_before(prompt_file: Path | None, no_docs: bool) -> None:
    """Run the earlier Wappi: its prompt from a file, and without the document tool."""
    if prompt_file:
        chat.PROMPT = prompt_file.read_text()
    if no_docs:
        tools.TOOLS.pop("search_documents", None)
        chat.SPECS[:] = [s for s in chat.SPECS if s["function"]["name"] != "search_documents"]


async def owner(name: str):
    async with SessionLocal() as s:
        home_id = await s.scalar(select(Home.id).where(Home.name == name))
        if home_id is None:
            raise SystemExit(f"no home named {name!r}")
        # A viewer is read-only, so every alert would be refused: measure as the owner.
        user_id = await s.scalar(
            select(HomeMember.user_id)
            .where(HomeMember.home_id == home_id, HomeMember.role != "viewer")
            .order_by(HomeMember.role.desc())
        )
    return home_id, user_id


def cells(items: list[dict]) -> list[str]:
    judged = [r for r in items if r["judge"]["verdict"] != "unjudged"]
    passed = sum(r["judge"]["verdict"] == "pass" for r in judged)
    agreed = sum(r["judge"]["agree"] and r["judge"]["judges"] == 3 for r in judged)
    means = [
        f"{statistics.mean(r['judge']['mean'][c] for r in judged):.2f}" if judged else "-"
        for c in CRITERIA
    ]
    return [
        str(len(items)),
        f"{sum(not r['bad'] for r in items)}/{len(items)}",
        f"{passed}/{len(judged)}",
        f"{agreed}/{len(judged)}",
        *means,
        str(sum(bool(r["lint"]) for r in items)),
    ]


def table(rows: list[dict]) -> str:
    by = defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)
    head = ["Nhóm", "Câu", "Kiểm tra không cần mô hình", "Judge đạt", "3/3 đồng thuận", *CRITERIA]
    lines = ["| " + " | ".join([*head, "Câu khó nghe"]) + " |", "|" + "---|" * (len(head) + 1)]
    for group, items in [("tất cả", rows), *by.items()]:
        lines.append("| " + " | ".join([group, *cells(items)]) + " |")
    return "\n".join(lines)


async def main(name: str, split: str, runs: int, only: str | None, out: Path, judged: bool) -> None:
    home_id, user_id = await owner(name)
    t = await truth(home_id)
    today = datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y")
    record()
    todo = [
        s
        for s in SCENARIOS
        if split in ("all", s.split) and (only is None or s.group == only or s.id == only)
    ]
    rows: list[dict] = []
    for _ in range(runs):
        for s in todo:
            EVIDENCE.clear()
            r = await ask(home_id, user_id, s.question)
            evidence = evidence_text()
            bad = evaluate(s.expect, r["text"], r, t)
            verdict = (
                await judge_all(s.question, r["text"], evidence, today)
                if judged and r["text"].strip()
                else {"mean": {}, "verdict": "unjudged", "judges": 0, "agree": True}
            )
            rows.append(
                {
                    "id": s.id,
                    "group": s.group,
                    "split": s.split,
                    "question": s.question,
                    "answer": r["text"],
                    "tools": [n for n, _ in r["tools"]],
                    "evidence": evidence,
                    "bad": bad,
                    "judge": verdict,
                    "lint": speak_lint(r["text"]),
                    "first_s": r["first_s"],
                    "total_s": round(r["total_s"], 1),
                    "usage": r["usage"],
                }
            )
            print(
                f"{s.id:<4} {'ok ' if not bad else 'BAD'} {verdict['verdict']:<8} {bad}", flush=True
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    print("\n" + table(rows))
    times = [r["total_s"] for r in rows]
    print(f"\nwhole answer: median {statistics.median(times):.1f}s, slowest {max(times):.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("home")
    ap.add_argument("--split", choices=["all", "tune", "held"], default="all")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", help="a group name or a scenario id")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--prompt-file", type=Path, help="run an earlier prompt (the before side)")
    ap.add_argument("--no-docs", action="store_true", help="without the document tool")
    a = ap.parse_args()
    as_before(a.prompt_file, a.no_docs)
    asyncio.run(main(a.home, a.split, a.runs, a.only, a.out, not a.no_judge))
