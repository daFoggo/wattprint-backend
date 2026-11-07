# WattPrint Copilot: developer guide

For developers who change or extend the Copilot. It describes the code as it is. The design and the reasons behind it are in [2026-11-07-copilot-skill-tool-registry-design.md](../superpowers/specs/2026-11-07-copilot-skill-tool-registry-design.md) (the query builder: [2026-11-06-copilot-text2sql-design.md](../superpowers/specs/2026-11-06-copilot-text2sql-design.md)).

## 1. What the Copilot is

The Copilot answers a household's questions about its electricity and runs its background jobs. All of it is one LangGraph graph, `copilot_graph` in `app/copilot/agents/router.py`. A run has one of four triggers: `chat` (a question to `POST /api/v1/copilot/ask`), `confirm` (the user said yes to a pending write), `schedule` (the nightly `daily_advice` run) and `event` (a finished conversation to summarise). One run is one request. There is no checkpointer: the conversation lives in `copilot.message` and `copilot.tool_call`.

The LLM (on OpenRouter) chooses and explains. It picks a skill when the search is unsure, picks a skill's tool calls and their arguments, and words the answer. It never sees the database and never writes SQL. Numbers come from tools: Python handlers that validate their arguments, read or write the home's data, and return data and facts. `guard_output` replaces a reply whose numbers are not in the tool results.

## 2. Map of the code

| Path | What it holds |
| --- | --- |
| `app/copilot/agents/router.py` | The graph: 11 nodes, the edges, the `_timed` wrapper |
| `app/copilot/agents/state.py` | `TurnInput`, `TurnState`, the LLM shapes (`Decision`, `QueryGoal`, `Unclear`, `Phrasing`, `Fact`) |
| `app/copilot/agents/base_agent.py` | `CopilotContext`: model, sessions, embedder, today |
| `app/copilot/agents/llm.py` | The OpenRouter model, `structured()`, `text()`, the prompt constants |
| `app/copilot/nodes/` | One file per node (`answer_node.py` holds two) |
| `app/copilot/skills/retrieval.py` | Skill search SQL, `case_of`, `load_skill` |
| `app/copilot/skills/chunker.py` | Skills and tools into chunks; `no_tone`, `content_hash` |
| `app/copilot/skills/catalog_sync.py` | `skills.yaml` + handlers into DB rows and vectors; `replace_chunks` |
| `app/copilot/skills/grounding.py` | `ungrounded()`: numbers of a text not found in the sources |
| `app/copilot/skills/query_planning.py`, `answer_facts.py` | `query_usage`: check the arguments, build facts from rows |
| `app/copilot/skills/motifs.py`, `rules.py`, `advice.py` | `daily_advice` logic: cycles, patterns, rules, pricing, ranking |
| `app/copilot/tools/registry.py` | `@handler`, `Handler`, `RunContext`, `FORBIDDEN_ARGS`, `LOCKED_WITH` |
| `app/copilot/tools/handlers/` | Tool handlers: `usage`, `billing`, `live`, `advice`, `memory` |
| `app/copilot/tools/sql_builder.py`, `catalog.py` | `QueryGoal` into one SELECT; the SQL guard; allowed tables and functions |
| `app/copilot/tools/db_connector.py` | Scope token, `copilot_tx` (read-only transaction), `run` |
| `app/copilot/tools/home_data.py` | Reads and writes on the home's data, shared by handlers |
| `app/copilot/tools/embedder.py` | bge-m3 embedder |
| `app/copilot/memory/short_term.py` | Conversation, messages, `tool_call` rows, `last_turn` |
| `app/copilot/memory/lexicon.py` | Household words to devices and device types (trigram match) |
| `app/copilot/memory/recall.py` | Long-term recall: other sessions' summaries, household facts |
| `app/copilot/config/` | `llm_config.yaml`, `prompts.yaml`, `skills.yaml`, `settings.py` |
| `app/copilot/utils/helpers.py` | `detect_lang`, `as_json` |
| `app/routers/copilot.py` | `/ask` (JSON or SSE), conversations, terms, rules, suggestions |
| `app/routers/copilot_skills.py` | Skills, tools, `/skills/try`, memory |
| `app/schemas/copilot.py`, `copilot_skills.py` | Request and response models |
| `app/models/copilot.py` | Tables of the `copilot` schema |
| `app/cli/copilot_run.py`, `copilot_skills.py` | Schedule/event runs; catalog sync |
| `alembic/versions/20261107_b7d3e9f2a6c1_copilot_skill_registry_and_memory.py` | Registry, chunks and memory tables |
| `langgraph.json` | `langgraph dev` entry (`copilot_graph`) |

## 3. The graph

```
START ─► ingress ─► load_context
                         │
     ┌───────────────────┼────────────────────┬───────────────────┐
     │ chat              │ schedule, event    │ confirm           │ declined, expired
     ▼                   │                    │                   │
rewrite_question         │                    │                   │
     ▼                   │                    │                   │
recall_memory            │                    │                   │
     ▼                   ▼                    ▼                   │
find_skills ────────► decide ──[plan]──────► act                  │
     │                 ▲  │                   │                   │
     │                 └──┼────── [retry] ────┤                   │
     │ [none]             │ [no plan]         │ [done]            │
     ▼                    │                   │                   │
generate_answer ◄─────────┴───────────────────┴───────────────────┘
     ▼
guard_output ─► suggest_followups ─► save_turn ─► END
```

Labels in brackets are conditions. Conditional edges:

- `route_after_context`: outcome `declined`/`expired` → `generate_answer`; trigger `confirm` → `act`; `schedule`/`event` → `decide`; else → `rewrite_question`.
- `route_after_search`: `retrieval == "none"` → `generate_answer`; `choose` → `decide`.
- `route_after_decide` (decision_node): a non-empty `plan` → `act`; else → `generate_answer`.
- `route_after_act` (action_node), `[retry]`: back to `decide` only for an agent skill whose last round has an error, no card, `rounds < skill.max_steps` and `failed_rounds < executor.max_failed_rounds`.

Paths by trigger:

| Trigger | Path |
| --- | --- |
| `chat` | ingress → load_context → rewrite_question → recall_memory → find_skills → decide ⇄ act → generate_answer → guard_output → suggest_followups → save_turn |
| `confirm` | ingress → load_context (loads the pending call) → act → generate_answer → … → save_turn. The API always sends `chat`; `load_context` switches to `confirm` when the request has `confirm_call_id` or the reply is a yes |
| `schedule` | ingress → load_context (`home_id`, `skill_code`) → decide (pipeline plan) → act → generate_answer (empty) → … → save_turn |
| `event` | as `schedule`, plus `conversation_id` (the session to summarise) |

`TurnState` keys that matter (`agents/state.py`):

- Input: `trigger`, `question`, `user_id`, `conversation_id`, `confirm_call_id`, `home_id`, `skill_code`.
- Context: `lang`, `user`, `home` (id, timezone, tariff, devices, `latest_date`, `tracked`, `memory_enabled`), `token` (scope token), `history`, `last_turn`.
- Understanding: `terms` (lexicon matches), `dates`, `standalone`, `rewrite`, `qvec`, `memory`.
- Choice: `candidates` (the top `skill_top_k`), `retrieval` (`choose` / `none` / `given`), `skill`.
- Execution: `plan`, `transcript` (agent rounds for the next LLM call), `rounds`, `failed_rounds`, `tool_data` (latest data by tool name), `card`, `api`, `outcome`.
- Reply: `answer`, `answer_source` (`llm` / `template`), `followups`, `message_id`.
- Appended by every node (reducer `operator.add`): `flags`, `results`, `facts`, `queries` (the `tool_call` rows to save), `steps`, `timings`.

`_timed` wraps every node when the graph is built. It measures the node's wall time and adds the node name to `steps` and `{"node", "ms"}` to `timings`. Both come back in the `/ask` response.

## 4. Nodes

**ingress** (`nodes/ingress_node.py`). Reads `trigger`, `question`, `user_id`. Writes `trigger`, cleaned `question`, `lang`, `flags`. No LLM. Guardrails: strips control characters; a chat message must be 1 to `limits.message_chars` (1000) characters (`RejectedError` 400); at most `limits.messages_per_minute` (20) per user per process (429); the `INJECTION` regex adds the `injection` flag. Schedule and event runs pass straight through with `lang = "vi"`.

**load_context** (`nodes/context_node.py`). Reads the input. Writes `user`, `home`, `conversation_id`, `history` (last 6 messages), `last_turn`, `token`, `rounds = 0`, `failed_rounds = 0`; for schedule/event `skill` and `retrieval = "given"`; for a confirmation `trigger = "confirm"`, `skill` and a one-call `plan` with `source: "confirm"`. No LLM. Guardrails: the user must be a home member and the conversation must be theirs (`LookupError`, 404). A pending call counts only with `ok IS NULL`, in this conversation, younger than `executor.pending_minutes` (10); otherwise `outcome = "expired"`. A short reply in `YES`/`NO` ("có", "ok", "không", "huỷ"…) answers the last turn's pending card; "no" sets the row's `ok` to false and `outcome = "declined"`. It issues a 5-minute scope token for the home.

**rewrite_question** (`nodes/rewrite_node.py`). Reads `question`, `history`, `last_turn`, `token`. Writes `terms`, `dates`, `standalone`, `rewrite` (`method`: none / rule / llm, `carried` devices). Links words of this question and the previous one through the lexicon, resolves fixed dates ("hôm qua", "tuần qua", "29/10") with `resolve_dates`, and appends `[device names; period]` to the standalone text. LLM only for a follow-up the rules cannot complete (`llm.REWRITE`); the rewrite is dropped if it adds a number (`ungrounded`).

**recall_memory** (`nodes/memory_node.py`). Reads `standalone`, `home`, `user`, `conversation_id`. Writes `qvec` (one embedding, reused by `find_skills`) and `memory`. No LLM. Reads nothing when `home.memory_enabled` is false. See section 9.

**find_skills** (`nodes/skill_search_node.py`). Reads `qvec`, `home`, `memory`, `last_turn`, `rewrite`. Writes `candidates`, `retrieval`, and a `skill_search` row in `queries`. No LLM. See section 8.

**decide** (`nodes/decision_node.py`). Reads `skill`, `candidates`, `retrieval`, `flags`, `transcript`, `results` and the payload fields. Writes `skill`, `plan`, `rounds`, and on rejections `transcript` and `failed_rounds`; `outcome` is `other`, `refused` or `no_tool`. LLM: the skill choice among the top-n candidates (`structured`, `SkillChoice`) on every chat turn, and one tool-calling round (`bind_tools`) for an agent skill. A pipeline skill gets a plan of all its tools with no LLM. Guardrails: a chosen code not among the candidates means none; the `injection` flag refuses an agent skill; calls to a tool outside the skill or with a `FORBIDDEN_ARGS` argument are rejected and shown to the LLM next round; a call identical to one that already succeeded is skipped; preset arguments are removed from the tool schema (`tool_spec`).

**act** (`nodes/action_node.py`). Reads `skill`, `plan`, `home`, `token`, `terms`, `tool_data`. Writes `results`, `queries`, `facts`, `api`, `tool_data`, `card`, `failed_rounds`, empties `plan`; for an agent skill appends to `transcript`. No LLM of its own (`phrase_suggestions` and `summarize_session` call it inside). Guardrails: see section 7.

**generate_answer** (`nodes/answer_node.py`). Reads `card`, `outcome`, `retrieval`, `results`, `facts`, `skill`, `home`. Writes `answer`, `answer_source`. `template()` answers without the LLM for cards, out-of-scope, declined/expired, failures, unknown devices and no data. Otherwise one `llm.text` call with `llm.ANSWER` and only the good results. If the call fails, the facts are read out. Schedule and event runs get an empty answer.

**guard_output** (`nodes/guard_node.py`). Reads `answer`, `answer_source`, `results`, `facts`, `question`, `standalone`. Writes `answer` (cut to 1200 characters) or, on a problem, the facts text with `answer_source = "template"` and `flags`. No LLM. Checks only LLM answers: `ungrounded:` (a number not in results, facts, question, today or latest date; integers up to 10 pass), `leak` (a UUID, SQL, or a reply starting with `{`/`[`), `false_claim` ("đã tạo", "I created"… with no successful `create_alert`).

**suggest_followups** (`nodes/answer_node.py`). Writes `followups`: the skill's first three `followups`, none with a card or on schedule/event runs. No LLM.

**save_turn** (`nodes/save_node.py`). Writes `message_id`. Puts the chosen skill code into the `skill_search` row, then saves the assistant message and every `queries` row (`short_term.save_reply`). Schedule/event runs save the rows with `message_id = NULL` and `home_id` set. A confirmed call updates its pending row (`update_id`) instead of adding one.

## 5. Agents: what "agent" means here

There is one graph, not a set of agents talking to each other. "Agent" means two things in the code: the `agents/` folder (graph wiring, state, context, LLM calls) and the `agent` mode of a skill, where the LLM calls the skill's tools (section 6).

`agents/router.py` builds the graph with `StateGraph(TurnState, context_schema=CopilotContext, input_schema=TurnInput)`. The API, the CLIs, the tests and `langgraph.json` all import `copilot_graph`, and call it with `ainvoke(inp, context=CopilotContext(...))`.

`agents/base_agent.py`, `CopilotContext` holds everything a run needs that is not state. Each field is swappable; `None` means the real one, built on first use:

| Field | Default | Accessor |
| --- | --- | --- |
| `chat_model` | `llm.chat_model()` (OpenRouter); `False` turns the LLM off | `model()`, `optional_model()` |
| `app_sessions` | `app.database.SessionLocal` | `app()` |
| `copilot_sessions` | `app.database.copilot_sessions()` (read-only login) | `copilot()` |
| `text_embedder` | `tools.embedder.default_embedder()` | `embedder()` |
| `today` | `COPILOT_TODAY`, else today in Asia/Ho_Chi_Minh | `local_today()` |

`optional_model()` is for wording only (advice, summaries): it returns `None` without an OpenRouter key, and the caller falls back to templates. `app/routers/copilot.py` `get_copilot_context()` returns a fresh `CopilotContext()`, or 503 while the Copilot is off.

`agents/llm.py`:

- `chat_model()`: `ChatOpenAI` on `OPENROUTER_BASE_URL` with `temperature`, `timeout_s` and `max_retries` from `llm_config.yaml`. `reasoning: false` sends `extra_body={"reasoning": {"enabled": False}}`, which turns off hidden reasoning tokens (about 9 s → 1.5 s per call).
- `structured(model, schema, system, payload)`: `with_structured_output(method="function_calling")`, the payload as one JSON user message, one retry on a validation error.
- `text(model, system, payload)`: a plain reply.
- `AGENT`, `SKILL_CHOICE`, `REWRITE`, `ANSWER`, `PHRASE`, `SUMMARIZE`: read from `prompts.yaml` at import, so a missing prompt fails at start.

| Prompt | Used by | Call |
| --- | --- | --- |
| `agent` (+ skill name, description, instructions) | `decide`, agent round | `bind_tools` |
| `skill_choice` | `decide._choose` | `structured(SkillChoice)` |
| `rewrite` | `rewrite_question` | `structured(Rewrite)` |
| `answer` | `generate_answer` | `text` |
| `phrase` | `phrase_suggestions` tool | `structured(Phrasing)` |
| `summarize` | `summarize_session` tool | `structured(SessionSummaryOut)` |

## 6. Skills

A skill is a goal: when to use it (description, examples), how it runs (`mode`), when it starts (`triggers`) and which tools it may use. Tables (`app/models/copilot.py`):

- `copilot.skill`: `home_id` (NULL = system skill), `code` (unique per home), `name`, `description`, `instructions`, `mode`, `triggers`, `schedule`, `max_steps` (default 4), `followups`, `based_on`, `enabled`, `version`, `embed_status`.
- `copilot.skill_tool`: `skill_id`, `tool_id`, `ord`, `preset` (arguments fixed by the skill).
- `copilot.skill_setting`: a home's on/off switch for a system skill.

Modes:

- `agent`: `decide` gives the LLM the skill's tools; `act` runs the calls; the loop repeats only to fix failed calls, up to `max_steps`.
- `pipeline`: `decide` plans every tool in `ord` order with empty arguments (`source: "pipeline"`); `act` runs them one by one, each reading earlier outputs from `rc.results`, and stops at the first failure. No LLM picks tools; pipeline writes run without confirmation.

Triggers: `chat` (only these are searched by `find_skills`), `schedule` (`copilot_run --skill`, `POST /copilot/suggestions/refresh`), `event` (`copilot_run --sessions`). The `schedule` column records the intended cron; the cron entry itself lives in the deployment (section 14).

System skills come from `app/copilot/config/skills.yaml`. `python -m app.cli.copilot_skills sync` (`catalog_sync.sync`) upserts tools and skills, bumps `version` on a change, rebuilds `skill_tool`, re-chunks and embeds only new texts, and disables rows that left the file. It never touches household rows.

Household skills come from the API (`POST /copilot/skills`, owner only). Rules in `app/routers/copilot_skills.py`: tools must be `user_selectable` (1 to 5), 2 to 30 examples, at most 20 skills per home, no links in instructions. A preset may only set arguments listed in the tool's `presettable`, its value is validated against the handler's field type, and device ids must belong to the home. Presets are stored in `skill_tool.preset`. `tools.registry.locked(preset)` returns the preset names plus `LOCKED_WITH` (a `device_ids`/`device_id` preset also locks `device_type_codes`). Those arguments are hidden from the LLM in `decide.tool_spec` and replaced in `act._run`, so a household skill can narrow a tool but never widen it. A home can also copy a system skill (`/skills/{id}/copy`) or add its own examples to one (`/skills/{id}/examples`, stored with its `home_id`, seen only by that home). `PUT /skills/{id}/enabled` writes a `skill_setting` row for a system skill and flips `skill.enabled` for a household one.

Current system catalog:

| Code | Mode | Triggers | Tools |
| --- | --- | --- | --- |
| `usage_query` | agent | chat | `query_usage` |
| `bill_explain` | agent | chat | `compute_bill`, `bill_by_tier`, `search_price`, `query_usage` |
| `forecast_bill` | pipeline | chat | `usage_to_date`, `forecast_usage`, `search_price`, `price_kwh` |
| `tier_guard` | pipeline | chat | `forecast_usage`, `search_price`, `tier_gap` |
| `savings_advice` | agent | chat | `read_suggestions` |
| `savings_tracking` | agent | chat | `get_savings` |
| `live_status` | agent | chat | `nilm_latest` |
| `alerts` | agent (`max_steps: 2`) | chat | `list_alerts`, `create_alert` |
| `energy_knowledge` | agent | chat | `search_knowledge` |
| `daily_advice` | pipeline | schedule, chat | `derive_cycles`, `detect_motifs`, `evaluate_rules`, `price_candidates`, `rank_candidates`, `phrase_suggestions`, `store_suggestions`, `measure_savings` |
| `session_summary` | pipeline | event | `read_session`, `summarize_session`, `store_session_memory` |

## 7. Tools

A tool row (`copilot.tool`) can only run its handler: `name`, `handler`, `parameters` and `side_effect` come from code on sync. `tools/registry.py`:

- `@handler(name, args=NoArgs, side_effect="read")` registers `async def fn(args, rc) -> dict` in `HANDLERS`. It asserts that the args model has no `FORBIDDEN_ARGS` field.
- `Handler`: `name`, `fn`, `args` (pydantic model), `side_effect`; `schema()` is the model's JSON Schema without titles, copied to `copilot.tool.parameters`.
- `RunContext`: what a handler may use: `ctx`, `home`, `token`, `lang`, `user`, `terms`, `question`, `conversation_id`, `results` (earlier outputs by tool name), `today`. None of it comes from the LLM.
- `FORBIDDEN_ARGS = {"home_id", "user_id", "token", "sql"}`; `LOCKED_WITH` as in section 6.
- `handlers()` imports `tools/handlers/` so every module registers.

A handler returns a dict with any of: `data` (what the LLM and the answer read), `facts` (`list[Fact]`, shown under the answer), `card` (an `Unclear` clarification), `ok: False` + `error`, `no_data`, `no_device`, `miss` (log a miss row), `sql`, `unit`, `ms`, `goal`, `assumptions`, `api` (extra `/ask` fields).

Read vs write: when the LLM asks for a `write` tool, `act` does not run it. It returns a `confirm` card (`call_id`, `tool`, `label`, `args`) and stores a `tool_call` row with `ok = NULL`. The app sends `POST /ask` with `confirm_call_id` (or the user types "có"); the next run loads that row, runs it with `source: "confirm"` and updates the same row. Pipeline writes run directly.

| Module | Tools (write in bold) |
| --- | --- |
| `handlers/usage.py` | `query_usage` (the safe Text2SQL path) |
| `handlers/billing.py` | `compute_bill`, `bill_by_tier`, `search_price`, `usage_to_date`, `forecast_usage` (registered read, stores a `ForecastSnapshot`), `price_kwh`, `tier_gap` |
| `handlers/live.py` | `nilm_latest`, `list_alerts`, **`create_alert`**, `search_knowledge` |
| `handlers/advice.py` | `read_suggestions`, `get_savings`, **`derive_cycles`**, **`detect_motifs`**, `evaluate_rules`, `price_candidates`, `rank_candidates`, `phrase_suggestions`, **`store_suggestions`**, **`measure_savings`** |
| `handlers/memory.py` | `read_session`, `summarize_session`, **`store_session_memory`** |

How `act` runs a call (`_run`): drop the locked arguments the LLM sent, lay the preset over them, validate with the handler's model (an error goes back as `invalid arguments: …`), stop an LLM write at the card, then run the handler under `asyncio.wait_for(timeout_ms)`. A timeout or exception becomes `ok: False` with the message; it never fails the turn. Agent skills run all reads of a round in parallel (`asyncio.gather`), then writes in order. Pipelines run in order. The LLM sees each result as JSON `data` (cut to 6000 characters) or `{"error": …}`, never SQL. Every call becomes a `tool_call` row (`tool`, `ok`, `sql_text`, `unit`, `duration_ms`, `input = {args, skill, data, error, goal, facts}`); unknown words and devices add a `miss` row.

## 8. Retrieval search

Chunker (`skills/chunker.py`, pure):

- `skill_chunks`: the sentences of `"name. description"` (split at `.?!;` or newlines, pieces under 40 characters merged, over 400 cut at words), then each example as written plus its toneless twin (`no_tone`: "Bếp tuần qua" → "bep tuan qua"), duplicates dropped. Instructions are not embedded.
- `tool_chunks`: `"label (name): description"` and one `"name.arg: description"` per described argument. They are stored and embedded, but `find_skills` searches skill chunks only.
- `content_hash(model, text)` (sha256): `replace_chunks` keeps rows whose hash is unchanged, so a second sync embeds nothing. A failed embedding leaves `embed_status = "failed"` until `/skills/{id}/reembed`.

Embedder (`tools/embedder.py`): `BAAI/bge-m3` through sentence-transformers, in process, CUDA if present else CPU, 1024 dimensions, normalised. `embed()` runs in a thread; `embed_query()` keeps an LRU cache of `embedding.cache_size` (2048) questions. `default_embedder()` is one per process. `app/main.py` warms it at startup (`_warm_embedder`, only when the Copilot is on).

Storage: `copilot.catalog_chunk` (`skill_id` or `tool_id`, `home_id` NULL for system text, `kind` description/example/tool/param, `text`, `content_hash`, `embedding vector(1024)`, `embed_status`) with an HNSW index (`vector_cosine_ops`, m 16, ef_construction 64).

The search (`skills/retrieval.py`, `SEARCH`): visible skills are enabled, `embed_status = 'ready'`, have `chat` in `triggers`, and are either system skills not switched off in `skill_setting` or this home's own. Take the 60 nearest ready chunks (system or this home's), keep the best cosine per skill, return the top `skill_top_k` (3, set in `llm_config.yaml`). `SET LOCAL hnsw.iterative_scan = relaxed_order` keeps the filter from emptying the HNSW result.

`case_of` with the values in `llm_config.yaml` `retrieval`:

| Case | Rule |
| --- | --- |
| `none` | top similarity < `choose_min_sim` (0.45): out of scope, no LLM call |
| `choose` | anything else: the model picks one of the top `skill_top_k` in `decide` |

There is no shortcut that takes the top hit without the model: a ranking can be close between, say, `usage_lookup` and `bill_explain`, and the model reads the examples of all n. Raise `skill_top_k` for a larger catalog; each extra candidate adds two examples to the prompt.

Extra rules in `nodes/skill_search_node.py`:

- Memory boost: a skill used in a recalled session gets `+0.01` (`MEMORY_BOOST`); it breaks ties.
- Previous skill: the last turn's skill is always a candidate (added when the search did not return it) and the case is `choose`. When `rewrite.carried` is set (a rule-completed follow-up) it goes first; otherwise it goes last.

Skill choice by the LLM (`decide._choose`): the payload has the standalone question, the last two messages and each candidate's code, name, description, `household` flag and up to two example questions as written (with tone marks, the home's own first, read from `catalog_chunk`). The prompt tells the model to prefer a household skill whose examples match. A code outside the candidates, or `"none"`, ends the turn with the out-of-scope template, except for a follow-up completed from the last turn or a question that names one of the home's devices: both are in scope, so the first candidate is taken.

## 9. Memory

Short-term memory is the conversation itself (`memory/short_term.py`):

- `open_conversation` creates or checks the conversation, returns the last 6 messages (`HISTORY_MESSAGES`) and adds the user's message.
- `last_turn` reads the previous assistant message's `tool_call` rows: the chosen skill (from `skill_search.input.chosen`), each call with its arguments and `ok`, and a pending write.
- `rewrite_node` uses it for follow-ups by rule. A question is a follow-up when it starts with "còn", "thế còn", "vậy còn", "and", "what about", "how about" (`FOLLOWUP`), or has at most four words, links no device itself and the last turn's `query_usage` had devices (`carried`). Then the standalone question is `"<question> — <previous question>"`. The LLM rewrite is the fallback.
- `memory/lexicon.py` links words to devices, device types, rooms and saved terms (`strict_word_similarity ≥ 0.6` on `copilot_ro.lexicon`, top 5 per kind). Terms are saved through `/copilot/terms`, also from the options of an `unknown_word` card.

Long-term memory is written by the `session_summary` pipeline (`tools/handlers/memory.py`):

1. `read_session`: the conversation's messages (empty when none is newer than the summary's `covers_until`) and, counted from `tool_call` rows rather than written by the LLM: skills and tools used, actions (`create_alert` ids), devices, periods, open items.
2. `summarize_session`: one `structured` call (`SessionSummaryOut`). Checks: emails and phone numbers become "…"; numbers not in the session's tool results become "…"; 600 characters max; facts are kept only with a key from `FACT_KEYS` and its value fields, a quote found in a user message, and ids (device, alert, suggestion) that exist in this home. `preference.lang` is detected from the user messages (two or more, one language), never taken from the LLM. Without a model the step fails and nothing is stored.
3. `store_session_memory`: embeds summary + topics, upserts `copilot.session_summary` by `conversation_id`, upserts `copilot.home_memory` facts (`fact.*` are home-wide, others per user); a repeated fact gains 0.1 confidence (max 1) and the conversation in `evidence`.

The session_closed sweep: `python -m app.cli.copilot_run --sessions` finds conversations of homes with `core.home.copilot_memory` on, quiet for `--idle-minutes` (30) and with messages newer than their summary, and runs `session_summary` on each with the `event` trigger.

Recall (`memory/recall.py`, called by `recall_memory`): summaries of the home's other sessions with cosine ≥ `memory_min_sim` (0.55), scored `sim × 0.5^(age_days / memory_half_life_days)` (14), top 3; facts of the home or this user with confidence ≥ 0.5, seen in the last 90 days, top 8. `decide` passes them as `memory` and `household_facts`; the prompt says memory is never a source of numbers. `PUT /copilot/memory/enabled` with false stops both recall and the sweep.

## 10. Guardrails summary

| Where | What it stops |
| --- | --- |
| `ingress` | Empty or long messages, control characters, flooding (rate limit), injection phrases (flag) |
| `load_context` | Other homes' conversations, stale or foreign confirmations (10 minutes, same conversation) |
| `decide` | Agent runs on an injection flag, skills outside the candidates, tools outside the skill, `home_id`/`user_id`/`token`/`sql` arguments, locked arguments (hidden), repeated calls |
| `act` | Invalid arguments (pydantic), preset overrides, LLM writes without a yes, slow tools (`timeout_ms`), SQL in what the LLM sees |
| `guard_output` | Ungrounded numbers, ids, SQL or JSON in the reply, claims of a change that did not happen |
| `query_usage` | See below |

The SQL guard inside `query_usage`: `query_planning.validate` checks the LLM's arguments against the linked terms and the home's devices, fills the period (at most 400 days) and may return a clarification card. `sql_builder.build` makes one SELECT with sqlglot; values are `$n` parameters, never text. `check_text(sql, "execute")` accepts one SELECT only, no write or DDL node, tables from `ALLOWED_TABLES["execute"]` (the `copilot_ro` views), functions from `FUNCTIONS`, and a literal `LIMIT` up to 1000. The query is `EXPLAIN`ed, then run in `db_connector.copilot_tx`: `READ ONLY`, `SET LOCAL ROLE wattprint_copilot_ro`, `statement_timeout = 5s`, `app.copilot_token` set so the `copilot_ro` views show only this home, always rolled back. `COPILOT_DATABASE_URL` must log in as `wattprint_copilot_ro` (`database.copilot_sessions` refuses another user). Household rules (`skills/rules.py`) compile to SQL that goes through the same `check_text` with the `evaluate_rules` table list.

## 11. API

All under `/api/v1`. Members read; writes marked (owner) need the home's owner. Endpoints that take the Copilot context answer 503 while it is off.

| Method and path | What it does |
| --- | --- |
| `POST /copilot/ask` | One chat run. Body: `question`, `conversation_id?`, `confirm_call_id?`. With `Accept: text/event-stream`: SSE events `step`, `token`, `result`, `card`, `done`, `error` |
| `GET /copilot/conversations` | The user's conversations |
| `GET /copilot/conversations/{id}/messages` | Messages of one conversation |
| `GET`, `POST /copilot/terms`; `PATCH`, `DELETE /copilot/terms/{id}` | Household words for devices and types |
| `GET`, `POST /copilot/rules`; `PATCH`, `DELETE /copilot/rules/{id}` | Household rules (owner; compiled and dry-run on save) |
| `GET /copilot/suggestions`; `POST /copilot/suggestions/{id}/feedback` | Saving suggestions; accept, reject, snooze, done |
| `POST /copilot/suggestions/refresh` | Runs `daily_advice` now (trigger `schedule`) |
| `GET /copilot/skills`; `GET /copilot/skills/{id}` | System and household skills (event skills hidden) |
| `POST /copilot/skills`; `PATCH`, `DELETE /copilot/skills/{id}` | Household skills (owner; saved and embedded before returning) |
| `PUT /copilot/skills/{id}/enabled` | Switch a skill on or off for the home (owner) |
| `POST /copilot/skills/{id}/examples`; `DELETE /copilot/skills/{id}/examples/{chunk_id}` | The home's own examples (owner) |
| `POST /copilot/skills/{id}/copy`; `POST /copilot/skills/{id}/reembed` | Copy a system skill; retry embedding (owner) |
| `POST /copilot/skills/try` | Which skills a question would find, with scores; runs nothing |
| `GET /copilot/tools` | Tools households can use, with their presettable fields |
| `GET /copilot/memory`; `DELETE /copilot/memory/facts/{id}`; `DELETE /copilot/memory`; `PUT /copilot/memory/enabled` | Long-term memory: read, forget one fact, forget all (owner), switch (owner) |

`AskOut` (`app/schemas/copilot.py`) carries `answer`, `facts`, `result` (rows and SQL), `clarification`, `confirm`, `suggestions`, `skill`, `retrieval` (case, standalone, candidates), `tools`, `steps`, `timings`, `followups`, `memory` and `message` (the mobile chat bubble). The app screens built on these endpoints are in `docs/copilot-tests/skills-ui/`: skills list and editor (`01`–`07`), the skill chip and the confirmation card in chat (`08`–`10`), the skill switch (`11`–`12`), advice refresh (`13`), memory (`14`) and rules (`15`–`17`).

## 12. How to

### Add a tool

1. Write the handler in a module of `app/copilot/tools/handlers/` (a new module must be imported in `handlers/__init__.py`). Describe every argument with `Field(description=…)`: it becomes the JSON Schema the LLM sees and a `param` chunk.
2. Take the home from `rc`, never from arguments. Read with `db.copilot_tx(rc.ctx.copilot(), rc.token)` (read-only, scoped) or `rc.ctx.app()()` filtered by `rc.home["id"]`.
3. Return `data`, and `facts` for the numbers the answer must show; `no_data` when empty.

```python
import datetime as dt
from pydantic import BaseModel, Field
from ...agents.state import Fact
from .. import db_connector as db
from .. import sql_builder as sql
from ..registry import RunContext, handler


class StandbyArgs(BaseModel):
    days: int = Field(default=7, ge=1, le=31, description="local days to look back")


@handler("standby_power", StandbyArgs)  # side_effect="write" if it changes data
async def standby_power(args: StandbyArgs, rc: RunContext) -> dict:
    since = sql.local_midnight(rc.today - dt.timedelta(days=args.days), rc.home["timezone"])
    async with db.copilot_tx(rc.ctx.copilot(), rc.token) as conn:
        w = await conn.fetchval("SELECT min(min_w) FROM copilot_ro.reading_1h "
                                "WHERE kind = 'main' AND bucket >= $1", since)
    if w is None:
        return {"data": {"standby_w": None}, "no_data": True}
    return {"data": {"standby_w": round(w)},
            "facts": [Fact(k="Công suất nền" if rc.lang == "vi" else "Standby", v=f"{w:.0f} W")]}
```

4. Add it under `tools:` in `config/skills.yaml` (`name` = handler name, `label_vi`, `label_en`, `category`, `description`, optional `timeout_ms`, `user_selectable`, `presettable`) and to a skill's `tools:` list.
5. Run `python -m app.cli.copilot_skills sync`. `test_sync_is_idempotent_and_every_tool_has_a_handler` fails if a YAML tool has no handler.
6. If the tool needs its own empty-result sentence, add it to `NO_DATA` and `TEMPLATES` in `nodes/answer_node.py`. A new write tool whose success may be announced ("đã tạo…") must be added to the `wrote` check in `nodes/guard_node.py`.

### Add a system skill

Add an entry under `skills:` in `config/skills.yaml`: `code`, `name`, `description` (embedded: write what the user asks, not how it works), `instructions` (for the LLM, not embedded), `tools` (a name, or `{tool: name, preset: {...}}`), optional `mode` (`pipeline`), `triggers`, `schedule`, `max_steps`, `followups`, and `examples` in Vietnamese and English (the chat skills have 3 to 12). Run `sync`. Check routing with `POST /copilot/skills/try` and the eval (section 13).

### Let households use a tool

Set `user_selectable: true` on the tool in `skills.yaml`, and list in `presettable` the arguments a household may fix (they must be fields of the handler's args model). Sync. The tool then appears in `GET /copilot/tools` and the skill editor.

### Change a prompt or a threshold

Prompts are in `config/prompts.yaml`; the user message of each call is JSON built by the node (`decision_node._payload`, `answer_node.generate_answer`, …), so a prompt that names a new key needs the node to send it. Model settings, retrieval thresholds, executor and limits are in `config/llm_config.yaml`. Both files are read at import: restart the API. After changing a threshold, run the eval; the test fixture lowers `choose_min_sim` and `memory_min_sim` to 0.3 for the fake embedder, so the tests do not measure bge-m3 routing.

## 13. Testing

Fakes in `tests/db/conftest.py`:

- `FakeEmbedder`: character trigrams of the toneless text hashed into 1024 dimensions. Same text scores 1, similar wording scores high. No model download.
- `FakeChatModel(calls, answer, choose, summary, rewrites)`: `calls` maps the user's original question to the first round's tool calls, a list of `(tool, args)` or a function of the decide payload (it sees `linked_terms`, so `typed(...)` in `test_copilot_ask.py` also checks word linking). Later rounds return no call. `choose` maps a question prefix to a skill code (default: the top candidate). `summary` builds the `SessionSummaryOut`; `rewrites` answers the rewrite call; any other structured call raises, so the caller's fallback runs. Free text returns `answer`. Every payload is kept in `model.payloads` for asserts.
- `demo` (session fixture): a scratch database migrated to head, REFIT House 2 from `tests/data/wattprint_dump_20261103.tar.gz` (29 Oct to 4 Nov 2026, today pinned to `DEMO_TODAY` 5 Nov), one owner, aggregates backfilled, catalog synced with `FakeEmbedder`. Tests pass `CopilotContext(chat_model=model, app_sessions=demo.sessions, copilot_sessions=demo.sessions, today=DEMO_TODAY, text_embedder=FakeEmbedder())` through `app.dependency_overrides[get_copilot_context]`.

| File | Covers |
| --- | --- |
| `tests/test_copilot_sql.py` | SQL builder and guard, no database |
| `tests/test_copilot_skills_unit.py` | Chunker, grounding, ingress rate limit |
| `tests/db/test_copilot_ask.py` | `/ask` on the demo home: usage questions, linking, NILM fallback, no data, unknown devices, out of scope, comparison, bill, follow-ups, SSE, 503 |
| `tests/db/test_copilot_advise.py` | `daily_advice` run, feedback and snooze, measured savings, rules (owner, dry run), refresh, no-key templates |
| `tests/db/test_copilot_skills.py` | Sync, household skills (validation, owner only, isolation), skill switch, write confirmation, injection, ungrounded numbers, scheduled `tool_call` rows, session summary memory, memory off |

Run them against the test container on port 5499 (the fixture creates and drops its own databases; `JWT_SECRET_KEY` comes from `.env`):

```bash
uv run pytest tests/test_copilot_sql.py tests/test_copilot_skills_unit.py
DATABASE_URL=postgresql+asyncpg://postgres:test@127.0.0.1:5499/postgres \
  uv run pytest tests/db/test_copilot_ask.py tests/db/test_copilot_advise.py tests/db/test_copilot_skills.py
```

The eval (`scripts/copilot_skill_eval.py`) uses the real model and bge-m3 (needs `OPENROUTER_*` and the `cpu` or `gpu` extra):

```bash
DATABASE_URL=postgresql+asyncpg://postgres:test@127.0.0.1:5499/postgres \
  uv run python scripts/copilot_skill_eval.py --setup          # prints the DSN of a new demo DB
uv run python scripts/copilot_skill_eval.py --dsn DSN [--only S01,M02]
```

`--setup` builds the demo home plus an empty second home and syncs the catalog with bge-m3. The run reads built queries through the `wattprint_copilot_ro` login with password `copilot` (the role is cluster-wide; set it once with `ALTER ROLE wattprint_copilot_ro LOGIN PASSWORD 'copilot'`). Cases are in `docs/copilot-tests/skill-tool-cases.yaml` (S01–S22 single questions, M01–M06 short- and long-term memory) with the expected skill, retrieval case, tool calls, arguments, numbers and latency budget. Results go to `docs/copilot-tests/skill-tool-results.json` and `.md` after every case: hit@1, hit@3, MRR, case accuracy, tool precision and recall, argument accuracy, write safety, latency.

## 14. Operations

On every deploy:

```bash
alembic upgrade head
python -m app.cli.copilot_skills sync     # tools and skills from skills.yaml, embedded
```

Cron (the API container or any host with the same env):

```
0 2 * * *     python -m app.cli.copilot_run --skill daily_advice   # every home with a main meter
*/10 * * * *  python -m app.cli.copilot_run --sessions             # summarise quiet conversations
```

`copilot_run` options: `--home ID` (one home), `--today YYYY-MM-DD`, `--no-llm` (template text), `--idle-minutes N`. It keeps going when one home fails and exits 1 if any did.

Environment (`app/config.py`, `.env.example`):

| Variable | Use |
| --- | --- |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | The chat model. Without both, `/ask` is 503 and advice uses templates |
| `OPENROUTER_BASE_URL` | Default `https://openrouter.ai/api/v1` |
| `COPILOT_DB_PASSWORD` | Set before migrating: gives `wattprint_copilot_ro` its login |
| `COPILOT_DATABASE_URL` | The read-only login (`docker-compose.yml` builds it from `COPILOT_DB_PASSWORD`). Empty = Copilot off |
| `COPILOT_TODAY` | Demo only: pin "today" |

The embedder needs torch and sentence-transformers from an extra: `uv sync --extra cpu` (the Dockerfile default) or `uv sync --extra gpu` (CUDA). bge-m3 loads from the Hugging Face cache on first use; the API warms it at startup. Without the extra the API still starts, logs the failed warm-up, and the Copilot fails on its first question. `sync` then stores the chunks with `embed_status = 'failed'`, and those skills are not found until a sync with the extra.
