"""add indexes for AI conversation foreign keys

Revision ID: c8d3f1a6b204
Revises: e5b8c2a7d914
"""

from alembic import op

revision = "c8d3f1a6b204"
down_revision = "e5b8c2a7d914"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_conversation_home_id", "ai_conversation", ["home_id"], schema="ai"
    )
    op.create_index(
        "ix_ai_conversation_user_id", "ai_conversation", ["user_id"], schema="ai"
    )
    op.create_index(
        "ix_ai_message_conversation_id", "ai_message", ["conversation_id"], schema="ai"
    )
    op.create_index(
        "ix_ai_tool_call_message_id", "ai_tool_call", ["message_id"], schema="ai"
    )


def downgrade() -> None:
    op.drop_index("ix_ai_tool_call_message_id", table_name="ai_tool_call", schema="ai")
    op.drop_index("ix_ai_message_conversation_id", table_name="ai_message", schema="ai")
    op.drop_index("ix_ai_conversation_user_id", table_name="ai_conversation", schema="ai")
    op.drop_index("ix_ai_conversation_home_id", table_name="ai_conversation", schema="ai")
