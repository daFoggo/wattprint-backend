# Spec: chat LLM fallback (lane M)

Goal (user): the Wappi chat works through OpenRouter or AstralX, using whichever is up (OpenRouter has answered 400
"Request path cannot be relayed" to every inference call since 2026-11-24).

Requirements
R1 Providers: OpenRouter and AstralX (`token.astralx.com.vn/v1`, model `byok/astral-x/claude-haiku-5-5`), both
   OpenAI-compatible with streaming, tool calls and usage; tried in `COPILOT_LLM_ORDER` (default openrouter first).
R2 A provider with no API key is skipped; none left means `CopilotUnavailableError` as before.
R3 A provider that fails before its first text delta hands over to the next; `turn` is reset. One that fails after
   text was yielded raises (the answer is partly out).
R4 A provider that is itself down (network, 5xx, 429, 401/402/403/404/408) rests at once for `COPILOT_LLM_COOLDOWN_S`
   (60 s). Another 4xx may be the request's fault: that provider rests only if the next one answers the same request
   (then it is the provider). When all are resting, they are tried anyway.
R5 The Llama Guard call (`guard.py`) stays on OpenRouter, fail-open as before, and is skipped while OpenRouter rests
   (AstralX has no guard model; the injection regex and the scoped tools still apply).
R6 `turn.usage["provider"]` names the answering provider and the message's `usage.providers` lists them, since AstralX
   reports no cost.

Areas of concern
- The cooldown map is per process: two api workers each learn on their own. `_down` is also set when a provider fails
  after speaking.
- AstralX's usage shape differs from OpenRouter's (no cost field): `turn.usage` consumers must not need `cost`.
- A tool-call stream that fails after tool deltas but before text is retried on the next provider from scratch.
Files: app/config.py, app/modules/copilot/services/llm.py, tests/test_copilot_llm.py, .env.example.
