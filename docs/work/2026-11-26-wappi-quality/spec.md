# Wappi quality: scenario eval, 3 judges, RAG on legal documents, speakable answers

Lane L. Record: user request 2026-11-26. Approved by the user in chat (RAG: research first, then build).

## Intent
The old eval (docs/chatbot-eval.md) scores 84/84 but only tests "does Wappi read the tool's number". Real users ask harder:
history, end-of-cycle estimates, "why did it rise", advice per device, a specific day or hour, vague or off-topic
questions, and questions about the law behind the bill. We need an eval that looks like real use, judges that are not
biased toward one model, and a loop that uses the scores to improve Wappi. Answers must also sound right when read
aloud (text to speech), not like chat text.

## Goals
1. ~60 scenarios by user need (history, estimate, cause, advice, day/hour data, comparison, vague, off-topic,
   legal/tariff documents, safety), each with a check that needs no model where a number can be checked.
2. Three judges from different model families (AstralX: claude-haiku-5-5, qwen3.8-27b, agentx_llm_pro), blind to who
   answered, scoring correctness, completeness, actionability, tone, speakability; majority verdict plus mean score.
3. A baseline run, changes, and a re-run on the same scenarios: a before/after table with real numbers only.
4. RAG over legal and tariff documents (tb_document/tb_chunk exist, empty): research report first, then build the
   smallest version that answers "what law/decision says X" with a citation.
5. Answers that read well aloud: short sentences, no brackets or symbols, numbers said once, one idea per sentence.

## Non-goals
Replacing the tools with RAG (figures still come from tools). A web UI for the eval. Fine-tuning. More providers.

## Anti-goals
Inventing numbers. A judge that sees which model answered. Tuning the prompt to the scenario wording (score only on
held-out phrasing, see Areas of concern). Quoting a law that was not read from a source.

## Constraints
Backend conventions (module layout, no module docstrings, UUIDv7 keys, Python 3.14). Provider: AstralX only (OpenRouter
returns 400). Citations use the existing source keys. Prior eval limits stay documented.

## Approaches (decided by me, the user handed over the how)
- Eval: standalone script + JSON scenario file, reuse eval_wappi helpers. Chosen: smallest, repeatable. Rejected: a
  pytest suite (calls paid models, not for CI).
- Judging: 3 judges blind, fixed rubric, temperature 0, JSON output. Chosen per user. Rejected: one judge (bias).
- RAG: pgvector or plain Postgres full-text? Decided after the research step; research report is the first deliverable.

## Areas of concern
- Judges share blind spots; report their agreement (how often all three agree) next to scores.
- Overfitting to the scenario set: split scenarios into tune and held-out sets; report both.
- AstralX embeddings and judges cost money: print token cost per run.
- Legal text copyright and accuracy: store only text read from the cited source, keep its URL and read date.
- Speakability rules must not change figures or units.
