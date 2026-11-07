"""What both Copilot agents share: the runtime context. The defaults are the real
connections and model; tests swap them."""

import datetime as dt
from dataclasses import dataclass
from typing import Any


@dataclass
class CopilotContext:
    """Runtime context of both graphs. The defaults are the real ones; tests swap them."""

    chat_model: Any = None  # None: the OpenRouter model, built on first use (llm.chat_model)
    app_sessions: Any = None  # None: app.database.SessionLocal
    copilot_sessions: Any = None  # None: app.database.copilot_sessions()
    today: dt.date | None = None  # None: today in Asia/Ho_Chi_Minh
    text_embedder: Any = None  # None: bge-m3 (tools.embedder), loaded on first use

    def embedder(self):
        if self.text_embedder is None:
            from ..tools.embedder import default_embedder

            self.text_embedder = default_embedder()
        return self.text_embedder

    def model(self):
        if self.chat_model is None:
            from .llm import chat_model

            self.chat_model = chat_model()
        return self.chat_model

    def optional_model(self):
        """The model for wording only (advice): None without one, then templates are used.
        `chat_model=False` turns the LLM off explicitly."""
        if self.chat_model is False:
            return None
        if self.chat_model is not None:
            return self.chat_model
        from ...config import settings

        return self.model() if settings.llm_enabled else None

    def app(self):
        if self.app_sessions is None:
            from ...database import SessionLocal

            self.app_sessions = SessionLocal
        return self.app_sessions

    def copilot(self):
        if self.copilot_sessions is None:
            from ...database import copilot_sessions

            self.copilot_sessions = copilot_sessions()
        return self.copilot_sessions

    def local_today(self) -> dt.date:
        if self.today is None:
            from ...config import settings
            from ...services.disaggregation import local_today

            return settings.copilot_today or local_today()
        return self.today
