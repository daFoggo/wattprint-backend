# Review: chat LLM fallback
R1 (sonnet, lane M): fix 1 (turn reset untested), 2 (real _attempt untested). Both added as tests (they passed at once:
the code was right). Minors fixed test-first: 3 cooldown stamped at the failure, 5 provider names lower-cased.
Rulings: 4 any CopilotUnavailableError cools the provider — the current outage is a 400, so 400 must count — cost: one
user's bad request moves everyone to the other provider for 60 s. 6 usage of a provider that failed before speaking is
dropped — cost: a little under-reported spend. Guard stays on OpenRouter (spec R5): with only an AstralX key, screening is off.

## Fix pass 2 (user: "tìm cách chuẩn nhất, không còn debt")
Ruling 4 replaced by a rule: hard failures (network, 5xx, 429, 401/402/403/404/408) rest at once; other 4xx rest the
provider only when the next provider answers the same request. Ruling 6 stays (a provider that fails before speaking
bills nothing we can read). Guard skipped while OpenRouter rests (no wait on a known-down provider). Message usage
lists the providers (cost gap from AstralX is explicit). Per-process cooldown: the compose runs one uvicorn process; with
more workers each learns on its own — harmless, no debt.
