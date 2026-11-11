"""initial auth module

Revision ID: e8d6cdf24fe4
Revises: cf93b7d8a102
"""

import sqlalchemy as sa

from alembic import op

revision = "e8d6cdf24fe4"
down_revision = "cf93b7d8a102"
branch_labels = None
depends_on = None

UUID7 = sa.text("uuidv7()")


def upgrade() -> None:
    op.create_table(
        "tb_users",
        sa.Column("id", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "tb_refresh_tokens",
        sa.Column("id", sa.Uuid(), server_default=UUID7, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.tb_users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )


def downgrade() -> None:
    op.drop_table("tb_refresh_tokens")
    op.drop_table("tb_users")
