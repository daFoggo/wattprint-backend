"""ai_speech: answers read aloud, kept so hearing one again is not voiced again; the tokens and
cost of each answer (ai_message.usage)

Revision ID: 4d1e7b9c2a58
Revises: 9b4e2d7f1a63
"""

import sqlalchemy as sa

from alembic import op

revision = "4d1e7b9c2a58"
down_revision = "9b4e2d7f1a63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_speech",
        sa.Column("message_id", sa.Uuid, nullable=False),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("voice", sa.String(64), nullable=False),
        sa.Column("audio", sa.LargeBinary, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_id", "lang", "voice", name="pk_ai_speech"),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["ai.ai_message.id"],
            name="fk_ai_speech_message_id_ai_message",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ai.ai_speech TO wattprint_app")
    op.add_column("ai_message", sa.Column("usage", sa.dialects.postgresql.JSONB), schema="ai")


def downgrade() -> None:
    op.drop_column("ai_message", "usage", schema="ai")
    op.drop_table("ai_speech", schema="ai")
