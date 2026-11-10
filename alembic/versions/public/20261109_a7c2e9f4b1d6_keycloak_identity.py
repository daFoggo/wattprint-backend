"""credentials move to Keycloak: drop refresh_tokens and users.hashed_password

Revision ID: a7c2e9f4b1d6
Revises: f3a9c1e5b7d2
Create Date: 2026-11-09

The external Keycloak subject is stored separately from the local integer user id.
"""

import sqlalchemy as sa

from alembic import op

revision = "a7c2e9f4b1d6"
down_revision = "f3a9c1e5b7d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("tb_refresh_tokens")
    op.drop_column("tb_users", "hashed_password")
    op.add_column("tb_users", sa.Column("keycloak_sub", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_tb_users_keycloak_sub", "tb_users", ["keycloak_sub"])


def downgrade() -> None:
    op.drop_constraint("uq_tb_users_keycloak_sub", "tb_users", type_="unique")
    op.drop_column("tb_users", "keycloak_sub")
    op.add_column("tb_users", sa.Column("hashed_password", sa.String(255), nullable=True))
    op.create_table(
        "tb_refresh_tokens",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
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
            ["user_id"],
            ["tb_users.id"],
            name="fk_tb_refresh_tokens_user_id_tb_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tb_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_tb_refresh_tokens_token_hash"),
    )
    # Same grant the roles migration (4d7b1e9a3c52) gave the app role on this table.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.tb_refresh_tokens TO wattprint_app")
