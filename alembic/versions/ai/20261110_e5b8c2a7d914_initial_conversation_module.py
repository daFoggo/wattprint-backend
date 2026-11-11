"""initialize AI conversation module and shared app/AI access

Revision ID: e5b8c2a7d914
Revises: d2f8a6c4b190
"""

import sqlalchemy as sa

from alembic import op

revision = "e5b8c2a7d914"
down_revision = "d2f8a6c4b190"
branch_labels = None
depends_on = None

UUID7 = sa.text("uuidv7()")

def upgrade() -> None:
    op.create_table(
        "ai_conversation",
        sa.Column("id", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("home_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_conversation"),
        sa.ForeignKeyConstraint(["home_id"], ["public.tb_home.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["public.tb_users.id"], ondelete="CASCADE"),
        schema="ai",
    )
    op.create_table(
        "ai_message",
        sa.Column("id", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_message"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai.ai_conversation.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "role IN ('user','assistant','tool','system')", name="ck_ai_message_role"
        ),
        schema="ai",
    )
    op.create_table(
        "ai_tool_call",
        sa.Column("id", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column(
            "input",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sql_text", sa.Text()),
        sa.Column("unit", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ai_tool_call"),
        sa.ForeignKeyConstraint(["message_id"], ["ai.ai_message.id"], ondelete="CASCADE"),
        schema="ai",
    )

    op.execute("REVOKE ALL ON ai.ai_conversation, ai.ai_message, ai.ai_tool_call FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ai.ai_conversation, "
        "ai.ai_message, ai.ai_tool_call TO wattprint_app, wattprint_ai"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE ALL ON ai.ai_conversation, ai.ai_message, ai.ai_tool_call "
        "FROM wattprint_app, wattprint_ai"
    )
    op.drop_table("ai_tool_call", schema="ai")
    op.drop_table("ai_message", schema="ai")
    op.drop_table("ai_conversation", schema="ai")
