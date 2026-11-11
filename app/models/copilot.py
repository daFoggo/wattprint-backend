import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base

_UUID_DEFAULT = text("gen_random_uuid()")
_NOW = text("now()")


class ScopeToken(Base):
    """Opaque short-lived token naming the one home a Copilot session may read.

    Issued and pruned by wattprint_app; the Copilot role cannot read this table and resolves
    a token only through copilot_ro.current_home().
    """

    __tablename__ = "tb_scope_token"
    __table_args__ = {"schema": "public"}

    token: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        server_default=text("now() + interval '5 minutes'"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class Conversation(Base):
    __tablename__ = "ai_conversation"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class Message(Base):
    __tablename__ = "ai_message"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','tool','system')", name="role"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai.ai_conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ToolCall(Base):
    __tablename__ = "ai_tool_call"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai.ai_message.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    sql_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)


class Suggestion(Base):
    __tablename__ = "tb_suggestion"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','shown','accepted','dismissed','done')", name="status"
        ),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="SET NULL"), index=True
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_alert.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    expected_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(16), default="proposed", server_default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class SuggestionFeedback(Base):
    __tablename__ = "tb_suggestion_feedback"
    __table_args__ = (
        CheckConstraint("action IN ('accept','ignore','done','dislike')", name="action"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_suggestion.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_users.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    note: Mapped[str | None] = mapped_column(Text)


class SavingsMeasure(Base):
    __tablename__ = "tb_savings_measure"
    __table_args__ = {"schema": "public"}

    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_suggestion.id", ondelete="CASCADE"), primary_key=True
    )
    baseline_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    actual_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    weather_adjusted_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    method: Mapped[str] = mapped_column(Text, default="M&V", server_default="M&V")
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
