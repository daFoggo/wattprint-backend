"""credentials move to Keycloak: drop refresh_tokens and users.hashed_password

Revision ID: a7c2e9f4b1d6
Revises: f3a9c1e5b7d2
Create Date: 2026-11-09

users.id must equal the Keycloak `sub`. Rows created before this migration (own-JWT era) keep their
old ids: such a user would get a 409 on first login. Dev data only: reset the database, or import
the Keycloak user with `id` = the old users.id.
"""

import sqlalchemy as sa

from alembic import op

revision = "a7c2e9f4b1d6"
down_revision = "f3a9c1e5b7d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_column("users", "hashed_password")


def downgrade() -> None:
    op.add_column("users", sa.Column("hashed_password", sa.String(255), nullable=True))
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    # Same grant the roles migration (4d7b1e9a3c52) gave the app role on this table.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.refresh_tokens TO wattprint_app")
