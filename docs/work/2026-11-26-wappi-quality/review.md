# Review: Wappi quality

Base: backend `d8df9411a1415938740c889b577ce8f0a43364ba` (clean tree). Snapshot after R1: `e2bb31bcd94b06d7a0ca5e7a76d40c4f410cb6e4`.

## R1 (full, opus)
Verdict: fix 1.
1. **Must** `documents.py` newest_tariff_only: "past" cues and decision numbers matched as substrings ("household" has "old", "cũng" has "cũ", "trước thuế", "100" has "10" from the title's date), so the old 6-tier decision reached current-price questions. Fixed: whole-word `PAST` regex (not "trước thuế" / "before tax"), decision number taken from `\d+/QĐ`-style codes only, compared as whole tokens; test with the six reviewer questions.
2. **Minor** embedding timeout 60 s vs chat's 20 s with 5 s connect. Fixed: same `httpx.Timeout`.
3. **Minor** embedding tokens not recorded in `ai_message.usage`. Fixed as the reviewer allowed: exception named in `.claude/rules/copilot.md` and a `shortcut:` with trigger in `documents.embed`.
4. **Minor** a judge answering `"choices": null` raised TypeError and stopped the run. Fixed: TypeError is caught; test added.

Ruling: embeddings go to OpenRouter first although the spec said AstralX only — the user asked for it ("dùng embedded từ openrouter đi, chỉ fallback về astralx"); cost if wrong: none, AstralX serves the same vectors.
Ruling: plan named two homes for the baseline; only REFIT House 2 ran — the user asked to run moderately; cost if wrong: no cross-home comparison.

## R2 (scoped, sonnet)
Verdict: ship. All four findings addressed. One Minor outside the fix diff: the past-cue regex missed accents typed as combining marks (NFD). Fixed in the Minor pass: the question is normalised to NFC before matching, test added.

## Done
Full pytest in the api container before the review fixes: 715 passed, 1 skipped, 18 deselected. After the fixes: the 62 tests of the touched areas pass; ruff check, ruff format and `check_boundaries.py` clean.
