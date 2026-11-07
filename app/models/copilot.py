import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    REAL,
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .knowledge import EMBEDDING_DIM

_UUID_DEFAULT = text("gen_random_uuid()")
_NOW = text("now()")


class ScopeToken(Base):
    """Opaque short-lived token naming the one home a Copilot session may read.

    Issued and pruned by wattprint_app; the Copilot role cannot read this table and resolves
    a token only through copilot_ro.current_home().
    """

    __tablename__ = "scope_token"
    __table_args__ = {"schema": "copilot"}

    token: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True,
        server_default=text("now() + interval '5 minutes'"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = {"schema": "copilot"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','tool','system')", name="role"),
        Index("ix_message_conversation_created", "conversation_id", text("created_at DESC")),
        {"schema": "copilot"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("copilot.conversation.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ToolCall(Base):
    __tablename__ = "tool_call"
    __table_args__ = {"schema": "copilot"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    # NULL for scheduled and event runs, which have no message (home_id says whose run it was)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("copilot.message.id", ondelete="CASCADE"), index=True
    )
    home_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    sql_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool | None] = mapped_column(Boolean)  # NULL: a write awaiting the user's yes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class Suggestion(Base):
    __tablename__ = "suggestion"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','shown','accepted','dismissed','done')", name="status"
        ),
        Index("ix_suggestion_home_status", "home_id", "status"),
        {"schema": "copilot"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.device.id", ondelete="SET NULL"), index=True
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("insight.alert.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    expected_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(16), default="proposed", server_default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("copilot.rule.id", ondelete="SET NULL")
    )
    motif_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("insight.motif_instance.id", ondelete="SET NULL")
    )
    # the facts shown to the user ("night load 2,729 W on 30 Oct vs 327 W usually")
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class SuggestionFeedback(Base):
    __tablename__ = "suggestion_feedback"
    __table_args__ = (
        CheckConstraint("action IN ('accept','ignore','done','dislike')", name="action"),
        {"schema": "copilot"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("copilot.suggestion.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    note: Mapped[str | None] = mapped_column(Text)


class SavingsMeasure(Base):
    __tablename__ = "savings_measure"
    __table_args__ = {"schema": "copilot"}

    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("copilot.suggestion.id", ondelete="CASCADE"), primary_key=True
    )
    baseline_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    actual_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    weather_adjusted_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    method: Mapped[str] = mapped_column(Text, default="M&V", server_default="M&V")
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Term(Base):
    """A household's own word: a device, a device type, a time window or a threshold.

    Unique per home on the match key (copilot_ro.match_key of the phrase). `target` by kind:
    device {device_id}, device_type {code}, time_window {start_hour, end_hour},
    threshold {measure, op, value}.
    """

    __tablename__ = "term"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('device','device_type','time_window','threshold')", name="kind"
        ),
        CheckConstraint("match_key <> ''", name="match_key"),
        UniqueConstraint("home_id", "match_key", name="uq_term_home_id"),
        {"schema": "copilot"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    phrase: Mapped[str] = mapped_column(Text)
    match_key: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    target: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_from_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("copilot.message.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_NOW, onupdate=func.now()
    )


class Rule(Base):
    """When a condition holds over a motif's instances, suggest a kind (copilot/utils/rules.py).

    home_id NULL = a shared expert rule, seeded from the code. Unique (home_id, name), NULLs equal.
    """

    __tablename__ = "rule"
    __table_args__ = {"schema": "copilot"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    motif: Mapped[str] = mapped_column(Text)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    suggest_kind: Mapped[str] = mapped_column(Text)
    compiled_sql: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    content_hash: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_NOW, onupdate=func.now()
    )


# --- skill and tool registry (spec 2026-11-07, section 2) ---


class Tool(Base):
    """One action the Copilot can run: a handler in code (app/copilot/tools/registry.py),
    described for the LLM and the app. Synced from app/copilot/config/skills.yaml."""

    __tablename__ = "tool"
    __table_args__ = (
        CheckConstraint("side_effect IN ('read','write')", name="side_effect"),
        UniqueConstraint("name", name="uq_tool_name"),
        {"schema": "copilot"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    name: Mapped[str] = mapped_column(Text)
    label_vi: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    handler: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    presettable: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    side_effect: Mapped[str] = mapped_column(String(8), default="read", server_default="read")
    user_selectable: Mapped[bool] = mapped_column(Boolean, default=False,
                                                  server_default=text("false"))
    timeout_ms: Mapped[int] = mapped_column(Integer, default=5000, server_default="5000")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_NOW, onupdate=func.now()
    )


class Skill(Base):
    """A goal: when to use it, the tools it may use, how it starts and how its tools run.

    home_id NULL = a system skill (from skills.yaml); else one household's (from the app).
    Unique (home_id, code), NULLs equal.
    """

    __tablename__ = "skill"
    __table_args__ = (
        CheckConstraint("mode IN ('agent','pipeline')", name="mode"),
        CheckConstraint("embed_status IN ('pending','ready','failed')", name="embed_status"),
        {"schema": "copilot"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    mode: Mapped[str] = mapped_column(String(8), default="agent", server_default="agent")
    triggers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=lambda: ["chat"],
                                                server_default="{chat}")
    schedule: Mapped[str | None] = mapped_column(Text)
    max_steps: Mapped[int] = mapped_column(SmallInteger, default=4, server_default="4")
    followups: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    based_on: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("copilot.skill.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    embed_status: Mapped[str] = mapped_column(String(8), default="pending",
                                              server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_NOW, onupdate=func.now()
    )


class SkillTool(Base):
    """A tool a skill may use: its order and the arguments the skill fixes (preset)."""

    __tablename__ = "skill_tool"
    __table_args__ = {"schema": "copilot"}

    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("copilot.skill.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("copilot.tool.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    ord: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    preset: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class SkillSetting(Base):
    """A home's switch for a system skill; no row = enabled."""

    __tablename__ = "skill_setting"
    __table_args__ = {"schema": "copilot"}

    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("copilot.skill.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean)


class CatalogChunk(Base):
    """A short embedded text of a skill or a tool (the search space of find_skills)."""

    __tablename__ = "catalog_chunk"
    __table_args__ = (
        CheckConstraint("(skill_id IS NULL) <> (tool_id IS NULL)", name="owner"),
        CheckConstraint("kind IN ('description','example','tool','param')", name="kind"),
        Index("ix_catalog_chunk_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_catalog_chunk_home_skill", "home_id", "skill_id"),
        {"schema": "copilot"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("copilot.skill.id", ondelete="CASCADE")
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("copilot.tool.id", ondelete="CASCADE"), index=True
    )
    home_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(12))
    ord: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    embed_status: Mapped[str] = mapped_column(String(8), default="pending",
                                              server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


# --- long-term memory (spec section 2.2) ---


class SessionSummary(Base):
    """One finished session, summarised by the session_summary skill."""

    __tablename__ = "session_summary"
    __table_args__ = (
        CheckConstraint("outcome IN ('resolved','partly','unresolved')", name="outcome"),
        Index("ix_session_summary_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_session_summary_home_ended", "home_id", text("ended_at DESC")),
        {"schema": "copilot"},
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("copilot.conversation.id", ondelete="CASCADE"), primary_key=True
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    turns: Mapped[int] = mapped_column(SmallInteger)
    summary: Mapped[str] = mapped_column(Text)
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    skills_used: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list,
                                                   server_default="{}")
    tools_used: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"))
    actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"))
    entities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"))
    open_items: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"))
    outcome: Mapped[str] = mapped_column(String(12))
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    covers_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_NOW, onupdate=func.now()
    )


class HomeMemory(Base):
    """A durable fact about a household (or one member), with the sessions it came from."""

    __tablename__ = "home_memory"
    __table_args__ = (
        CheckConstraint("kind IN ('preference','interest','commitment','fact')", name="kind"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        {"schema": "copilot"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(12))
    key: Mapped[str] = mapped_column(Text)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evidence: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID), default=list,
                                                      server_default="{}")
    confidence: Mapped[float] = mapped_column(REAL, default=0.6, server_default="0.6")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
