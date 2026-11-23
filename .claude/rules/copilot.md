---
paths:
  - "app/modules/copilot/**"
---

# Copilot (Wappi): rules an agent must not miss

Source of truth: README "Copilot (Wappi)", docs/database-design-guide.md 3.4. This card is the short version.

- Tools first: every number comes from a deterministic tool; the model only plans and explains, and each tool call stores its SQL and units.
- Tools read only the asking home, whatever the model is told; text2sql gets a 5-minute scope token, set as a bind parameter with `is_local = true`, and `copilot_ro` fails closed (0 rows) without it.
- Personal data (phone, ID, email, card, account numbers) is replaced by a label before a question is stored or sent (`services/privacy.py`); injection is declined and harmful questions screened (`services/guard.py`). Keep both on every new path into the LLM.
- Without its key an endpoint answers 503 (`copilot_unavailable`, `voice_unavailable`, `weather_unavailable`), never a crash or empty data.
- Record tokens and cost in `ai.ai_message.usage`; keep the prompt's start stable so it stays cacheable.
