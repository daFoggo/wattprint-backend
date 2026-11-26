# Wappi quality Implementation Plan

> Execution: native (sdlc `build` is inline). Steps use checkboxes.

**Goal:** a realistic scenario eval with 3 blind judges, RAG over legal/tariff documents, and speakable answers, with a measured before/after.

**Architecture:** three scripts in `scripts/` (scenarios, judges, runner) reuse `eval_wappi.ask/truth`. RAG is a copilot service (`documents.py`) + one tool (`search_documents`) over the existing `tb_document`/`tb_chunk` (pgvector 1024-d, generated `tsv`), hybrid rank by Postgres full text + cosine. Speakability = prompt rules + a deterministic lint the eval reports.

**Tech Stack:** FastAPI, SQLAlchemy async, pgvector 0.8.1, AstralX (chat, `astralx-embed`), pytest.

**Spec:** `docs/work/2026-11-26-wappi-quality/spec.md`
**Base:** backend `d8df9411a1415938740c889b577ce8f0a43364ba` (clean tree).

## Global Constraints
- Provider AstralX only; judges: `claude-haiku-5-5`, `qwen3.8-27b`, `agentx_llm_pro` (ids as AstralX lists them under `byok/astral-x/`), temperature 0, JSON output.
- No module docstrings; imports per `.claude/rules`; UUIDv7 keys; Python 3.14; `scripts/check_boundaries.py` passes.
- Figures only from tools or checked services; never invent numbers; report real numbers and "chưa đo" otherwise.
- Documents: store only text read from the cited source; keep `source_url`, `version`, read date in `license_note`.

## Review Focus
- A judge returns invalid JSON or times out → that judge is dropped for the item and counted, never scored 0.
- All three judges fail → item is "unjudged", excluded from means, listed in the report.
- Scenario text leaks the expected answer to the judge → judges get question + answer + rubric only, never the model name or tool trace.
- RAG returns a chunk from a superseded document (QĐ 1279 vs 2892) → retrieval prefers the newest `published_at` per topic and answers name the document code.
- Question on a law Wappi has no document for → answer says it does not have it, no invented article number.
- Speakability rules change a figure or unit → lint test asserts figures and units survive.

---

### Task 1: Judges
**Files:** Create `scripts/wappi_judges.py`; Test `tests/test_wappi_judges.py`
**Produces:** `CRITERIA = ("correct","complete","actionable","tone","speakable")`; `async def judge(client, model: str, question: str, answer: str) -> dict[str,int] | None` (1-5 per criterion, None on invalid output); `def combine(votes: list[dict|None]) -> dict` returning `{"mean": {criterion: float}, "verdict": "pass"|"fail"|"unjudged", "judges": n_ok, "agree": bool}`; pass = majority of valid judges give every criterion ≥ 4 on correct and mean of all ≥ 3.5.
- [ ] Tests: `test_combine_majority_pass`, `test_combine_drops_invalid_judge` (one None → judges == 2), `test_combine_all_invalid_is_unjudged`, `test_judge_prompt_hides_model_and_tools` (prompt contains question and answer only).
- [ ] Implement `judge` via AstralX `/chat/completions` (reuse `settings.astralx_*`), rubric in the system prompt, ask JSON only.
- [ ] Run `docker compose exec -T api pytest -q tests/test_wappi_judges.py` → pass.

### Task 2: Scenarios and runner
**Files:** Create `scripts/wappi_scenarios.py`, `scripts/wappi_eval.py`; Test `tests/test_wappi_scenarios.py`
**Consumes:** `scripts.eval_wappi.ask(home_id, user_id, question) -> dict` (keys tools, watches, text), `truth(home_id)`, `near/amounts/kwh`.
**Produces:** `SCENARIOS: list[Scenario]` (`Scenario(id, group, question, split: "tune"|"held", check: Callable|None)`), ~60 items over groups history, estimate, cause, advice, day_hour, compare, tariff_doc, vague, offtopic, safety, alert; `python -m scripts.wappi_eval "<home>" [--split held] [--runs 1] --out docs/eval/<name>.json` writes per-item answer, tool names, deterministic check, judge scores, speak-lint, cost; prints a table per group.
- [ ] Tests: ids unique, every group ≥ 4 items, ≥ 30% held split, `tariff_doc` items carry an expected document code.
- [ ] Implement scenarios, then runner (3 judges in parallel per item, blind).
- [ ] Baseline: run on REFIT House 2 and Plegma House 1, save `docs/eval/baseline-2026-11-26.json`, write the table into `docs/chatbot-eval.md` as "Mốc 2".

### Task 3: RAG research report
**Files:** Create `docs/rag-research.md`
- [ ] Read the sources listed in `docs/legal-basis.md` and the session-collected links; list each candidate document with URL, what it answers, read status (read in full / search result only).
- [ ] Decide chunking, embedding (`astralx-embed`, 1024-d), hybrid ranking, citation format, refresh policy; record what was measured (retrieval hit rate on 15 questions) and what was not.

### Task 4: RAG build
**Files:** Create `scripts/ingest_documents.py`, `app/modules/copilot/services/documents.py`; Modify `services/tools.py` (tool `search_documents`, SOURCES key per document), `services/chat.py` (prompt line); Test `tests/test_copilot_documents.py`
**Produces:** `async def search(s: AsyncSession, query: str, lang: str, k: int = 4) -> list[Passage]` (`Passage(title, code, url, text, score)`); `def chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]`.
- [ ] Tests (fake embedder): `test_chunk_overlap_and_size`, `test_search_prefers_newer_tariff_document`, `test_search_empty_when_no_match`, `test_tool_returns_cite_keys`.
- [ ] Implement ingest (text from files under `docs/sources/`, read-only), search (FTS + cosine, reciprocal rank), tool + prompt: "legal/tariff questions: call search_documents; quote only returned text".
- [ ] Ingest and run the tariff_doc scenarios; record hit rate.

### Task 5: Speakable answers
**Files:** Modify `services/chat.py` PROMPT; Create `scripts/wappi_speak.py` (lint: `def speak_lint(text: str) -> list[str]`); Test `tests/test_wappi_speak.py`
- [ ] Tests: `test_lint_flags_long_sentence` (> 25 words), `test_lint_flags_parentheses_and_slash`, `test_rules_keep_figures_and_units`.
- [ ] Prompt rules: one idea per sentence, ≤ 20 words, no brackets/dashes/colons mid-sentence, say a figure once, round spoken figures, open with the answer, end with one suggestion.
- [ ] Re-run eval; compare lint violations and judge "speakable" before/after.

### Task 6: Improve loop and report
- [ ] Read failing and low-score items per group, fix prompt/tools (each change one commit-sized step), re-run `--split tune` after each, `--split held` once at the end.
- [ ] Write before/after table (tune and held, judge agreement, cost, latency) into `docs/chatbot-eval.md`; list what stayed weak.
- [ ] Full `pytest`, verify command, review loop R1–R3 per sdlc.

## Self-review
Spec coverage: goals 1→T2, 2→T1, 3→T2/T6, 4→T3/T4, 5→T5. Types: `judge`/`combine` names used in T2 as defined in T1. Held-out split guards against tuning to scenario wording (spec concern).

## Departures from the plan (updated during the build, 2026-11-26)

- **Embeddings**: `baai/bge-m3` via OpenRouter first, AstralX `astralx-embed` as fallback (order of `copilot_llm_order`); both return the same vectors (cosine 1.0000), so no second vector column. `documents.embed` hands over like chat does; vectors of the wrong size count as a provider failure.
- **Passage** is `(doc_id, title, url, version, doc_type, published_at, text, score)`; there is no `code` field (the `Document` table has no code column; the number is in the title). `search(s, question, k, embedder, max_distance)` has no `lang`.
- **Judges** get the tools' results and today's date (`judge_all(question, answer, evidence, today)`): without them correct answers about 2026 decisions scored 1-3. The runner records tool results by wrapping `chat.run_tool`; `--prompt-file` and `--no-docs` re-run the earlier Wappi for the before side.
- **Past-tariff rule**: an older tariff decision is returned when the question names its number or year or asks about the past (vi and en cues).
- **Speakable lint** (`wappi_speak.py`) was built in Task 2 because the runner reports it; Task 5 only changed the prompt.
- **Task 6** ran three prompt variants and two prompt re-checks; the final prompt (v5) is measured by group only (see docs/chatbot-eval.md). Run cost was kept low on the user's request: one home, one run per variant.
