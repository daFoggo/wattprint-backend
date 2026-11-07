"""Copilot skill and tool registry, embedded chunks, and long-term memory.

Spec: docs/superpowers/specs/2026-11-07-copilot-skill-tool-registry-design.md (sections 2 and 2.2).

- copilot.tool, copilot.skill, copilot.skill_tool, copilot.skill_setting: what the Copilot can do
  (tools, from code) and the goals it serves (skills: system, home_id NULL, or a household's).
- copilot.catalog_chunk: the embedding space (bge-m3, 1024 dimensions, as knowledge.chunk).
- copilot.session_summary, copilot.home_memory: long-term memory written by the session_summary
  skill; core.home.copilot_memory switches it off for a home.
- copilot.tool_call: rows of scheduled runs have no message (home_id instead), and a write waiting
  for the user's confirmation has ok = NULL.
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision = "b7d3e9f2a6c1"
down_revision = "6c2e8f1a4b90"
branch_labels = None
depends_on = None

APP = "wattprint_app"
TABLES = ("copilot.tool", "copilot.skill", "copilot.skill_tool", "copilot.skill_setting",
          "copilot.catalog_chunk", "copilot.session_summary", "copilot.home_memory")
CODE = r"^[a-z][a-z0-9_]{2,63}$"


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False,
                     server_default=sa.text("now()"))


def _hnsw(name: str, table: str) -> None:
    op.create_index(name, table, ["embedding"], schema="copilot", postgresql_using="hnsw",
                    postgresql_with={"m": 16, "ef_construction": 64},
                    postgresql_ops={"embedding": "vector_cosine_ops"})


def _registry() -> None:
    op.create_table(
        "tool",
        _uuid_pk(),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("label_vi", sa.Text, nullable=False),
        sa.Column("label_en", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("handler", sa.Text, nullable=False),
        sa.Column("parameters", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("presettable", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("side_effect", sa.String(8), nullable=False, server_default="read"),
        sa.Column("user_selectable", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("timeout_ms", sa.Integer, nullable=False, server_default="5000"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"name ~ '{CODE}'", name="ck_tool_name"),
        sa.CheckConstraint("side_effect IN ('read','write')", name="ck_tool_side_effect"),
        sa.CheckConstraint("timeout_ms BETWEEN 100 AND 30000", name="ck_tool_timeout_ms"),
        sa.CheckConstraint("char_length(description) <= 600", name="ck_tool_description"),
        sa.UniqueConstraint("name", name="uq_tool_name"),
        schema="copilot",
    )
    op.create_table(
        "skill",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID),  # NULL: a system skill
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("instructions", sa.Text, nullable=False, server_default=""),
        sa.Column("mode", sa.String(8), nullable=False, server_default="agent"),
        sa.Column("triggers", ARRAY(sa.Text), nullable=False, server_default="{chat}"),
        sa.Column("schedule", sa.Text),
        sa.Column("max_steps", sa.SmallInteger, nullable=False, server_default="4"),
        sa.Column("followups", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("based_on", sa.UUID),
        sa.Column("created_by", sa.UUID),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("embed_status", sa.String(8), nullable=False, server_default="pending"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"code ~ '{CODE}'", name="ck_skill_code"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 60", name="ck_skill_name"),
        sa.CheckConstraint("char_length(description) BETWEEN 1 AND 600",
                           name="ck_skill_description"),
        sa.CheckConstraint("char_length(instructions) <= 500", name="ck_skill_instructions"),
        sa.CheckConstraint("mode IN ('agent','pipeline')", name="ck_skill_mode"),
        sa.CheckConstraint("triggers <@ ARRAY['chat','schedule','event']::text[] "
                           "AND cardinality(triggers) > 0", name="ck_skill_triggers"),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 6", name="ck_skill_max_steps"),
        sa.CheckConstraint("cardinality(followups) <= 3", name="ck_skill_followups"),
        sa.CheckConstraint("embed_status IN ('pending','ready','failed')",
                           name="ck_skill_embed_status"),
        # households make chat skills the LLM drives; pipelines and schedules are system skills
        sa.CheckConstraint("home_id IS NULL OR (mode = 'agent' AND triggers = ARRAY['chat'])",
                           name="ck_skill_household"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_skill_home_id_home"),
        sa.ForeignKeyConstraint(["based_on"], ["copilot.skill.id"], ondelete="SET NULL",
                                name="fk_skill_based_on_skill"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL",
                                name="fk_skill_created_by_users"),
        schema="copilot",
    )
    op.execute("ALTER TABLE copilot.skill ADD CONSTRAINT uq_skill_home_id "
               "UNIQUE NULLS NOT DISTINCT (home_id, code)")
    op.create_table(
        "skill_tool",
        sa.Column("skill_id", sa.UUID, primary_key=True),
        sa.Column("tool_id", sa.UUID, primary_key=True),
        sa.Column("ord", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("preset", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["skill_id"], ["copilot.skill.id"], ondelete="CASCADE",
                                name="fk_skill_tool_skill_id_skill"),
        sa.ForeignKeyConstraint(["tool_id"], ["copilot.tool.id"], ondelete="RESTRICT",
                                name="fk_skill_tool_tool_id_tool"),
        schema="copilot",
    )
    op.create_index("ix_skill_tool_tool_id", "skill_tool", ["tool_id"], schema="copilot")
    op.create_table(
        "skill_setting",
        sa.Column("home_id", sa.UUID, primary_key=True),
        sa.Column("skill_id", sa.UUID, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_skill_setting_home_id_home"),
        sa.ForeignKeyConstraint(["skill_id"], ["copilot.skill.id"], ondelete="CASCADE",
                                name="fk_skill_setting_skill_id_skill"),
        schema="copilot",
    )
    op.create_table(
        "catalog_chunk",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("skill_id", sa.UUID),
        sa.Column("tool_id", sa.UUID),
        sa.Column("home_id", sa.UUID),  # NULL: every home; set: only that home
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("ord", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1024)),
        sa.Column("embed_status", sa.String(8), nullable=False, server_default="pending"),
        _ts("created_at"),
        sa.CheckConstraint("(skill_id IS NULL) <> (tool_id IS NULL)",
                           name="ck_catalog_chunk_owner"),
        sa.CheckConstraint("kind IN ('description','example','tool','param')",
                           name="ck_catalog_chunk_kind"),
        sa.CheckConstraint("char_length(text) BETWEEN 1 AND 400", name="ck_catalog_chunk_text"),
        sa.CheckConstraint("embed_status IN ('pending','ready','failed')",
                           name="ck_catalog_chunk_embed_status"),
        sa.CheckConstraint("embed_status <> 'ready' OR embedding IS NOT NULL",
                           name="ck_catalog_chunk_ready"),
        sa.ForeignKeyConstraint(["skill_id"], ["copilot.skill.id"], ondelete="CASCADE",
                                name="fk_catalog_chunk_skill_id_skill"),
        sa.ForeignKeyConstraint(["tool_id"], ["copilot.tool.id"], ondelete="CASCADE",
                                name="fk_catalog_chunk_tool_id_tool"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_catalog_chunk_home_id_home"),
        schema="copilot",
    )
    _hnsw("ix_catalog_chunk_embedding", "catalog_chunk")
    op.create_index("ix_catalog_chunk_home_skill", "catalog_chunk", ["home_id", "skill_id"],
                    schema="copilot")
    op.create_index("ix_catalog_chunk_tool_id", "catalog_chunk", ["tool_id"], schema="copilot")


def _memory() -> None:
    op.add_column("home", sa.Column("copilot_memory", sa.Boolean, nullable=False,
                                    server_default=sa.text("true")), schema="core")
    op.create_table(
        "session_summary",
        sa.Column("conversation_id", sa.UUID, primary_key=True),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("user_id", sa.UUID, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("turns", sa.SmallInteger, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("topics", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("skills_used", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("tools_used", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("actions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("entities", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("open_items", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("outcome", sa.String(12), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("covers_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("char_length(summary) <= 600", name="ck_session_summary_summary"),
        sa.CheckConstraint("cardinality(topics) <= 5", name="ck_session_summary_topics"),
        sa.CheckConstraint("outcome IN ('resolved','partly','unresolved')",
                           name="ck_session_summary_outcome"),
        sa.ForeignKeyConstraint(["conversation_id"], ["copilot.conversation.id"],
                                ondelete="CASCADE",
                                name="fk_session_summary_conversation_id_conversation"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_session_summary_home_id_home"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_session_summary_user_id_users"),
        schema="copilot",
    )
    _hnsw("ix_session_summary_embedding", "session_summary")
    op.execute("CREATE INDEX ix_session_summary_home_ended ON copilot.session_summary "
               "(home_id, ended_at DESC)")
    op.create_table(
        "home_memory",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("user_id", sa.UUID),  # NULL: the whole home
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("evidence", ARRAY(sa.UUID), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.REAL, nullable=False, server_default="0.6"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        _ts("created_at"),
        sa.CheckConstraint("kind IN ('preference','interest','commitment','fact')",
                           name="ck_home_memory_kind"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_home_memory_confidence"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_home_memory_home_id_home"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_home_memory_user_id_users"),
        schema="copilot",
    )
    op.execute("ALTER TABLE copilot.home_memory ADD CONSTRAINT uq_home_memory_home_id "
               "UNIQUE NULLS NOT DISTINCT (home_id, user_id, key, value)")


def _tool_call() -> None:
    op.alter_column("tool_call", "message_id", nullable=True, schema="copilot")
    op.alter_column("tool_call", "ok", nullable=True, schema="copilot")  # NULL: awaiting a yes
    op.add_column("tool_call", sa.Column("home_id", sa.UUID), schema="copilot")
    op.create_foreign_key("fk_tool_call_home_id_home", "tool_call", "home", ["home_id"], ["id"],
                          source_schema="copilot", referent_schema="core", ondelete="CASCADE")
    op.create_index("ix_tool_call_home_id", "tool_call", ["home_id"], schema="copilot")
    op.add_column("tool_call", sa.Column("created_at", sa.DateTime(timezone=True),
                                         nullable=False, server_default=sa.text("now()")),
                  schema="copilot")


def upgrade() -> None:
    _registry()
    _memory()
    _tool_call()
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP}")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {APP}")
    op.execute("DELETE FROM copilot.tool_call WHERE message_id IS NULL OR ok IS NULL")
    op.drop_column("tool_call", "created_at", schema="copilot")
    op.drop_index("ix_tool_call_home_id", "tool_call", schema="copilot")
    op.drop_constraint("fk_tool_call_home_id_home", "tool_call", schema="copilot")
    op.drop_column("tool_call", "home_id", schema="copilot")
    op.alter_column("tool_call", "ok", nullable=False, schema="copilot")
    op.alter_column("tool_call", "message_id", nullable=False, schema="copilot")
    for table in ("home_memory", "session_summary", "catalog_chunk", "skill_setting",
                  "skill_tool", "skill", "tool"):
        op.drop_table(table, schema="copilot")
    op.drop_column("home", "copilot_memory", schema="core")
