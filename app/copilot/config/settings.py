"""The Copilot's configuration: the YAML files next to this one, plus the app's env settings
(app/config.py: OPENROUTER_*, COPILOT_DATABASE_URL, COPILOT_TODAY), re-exported as `settings`."""

from pathlib import Path
from typing import Any

import yaml

from ...config import settings

HERE = Path(__file__).parent


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


LLM: dict[str, Any] = _load("llm_config.yaml")
PROMPTS: dict[str, str] = _load("prompts.yaml")

__all__ = ["LLM", "PROMPTS", "settings"]
