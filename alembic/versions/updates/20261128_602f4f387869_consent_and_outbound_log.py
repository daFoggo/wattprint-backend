"""consent per purpose (append-only), the outbound log, and alert mail off by default

Revision ID: 602f4f387869
Revises: 5a085853fca0
"""

import sqlalchemy as sa

from alembic import op

revision = "602f4f387869"
down_revision = "5a085853fca0"
branch_labels = None
depends_on = None

APP = "wattprint_app"
NOW = sa.text("now()")
UUID7 = sa.text("uuidv7()")


def upgrade() -> None:
    op.create_table(
        "tb_consent",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=UUID7),
        sa.Column(
            "user_id",
            sa.Uuid,
            sa.ForeignKey("public.tb_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("granted", sa.Boolean, nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("purpose IN ('wappi','voice','email')", name="purpose"),
        schema="public",
    )
    op.create_index(
        "ix_tb_consent_user_purpose_created",
        "tb_consent",
        ["user_id", "purpose", sa.text("created_at DESC")],
        schema="public",
    )
    op.create_table(
        "tb_outbound_log",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=UUID7),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column(
            "user_id", sa.Uuid, sa.ForeignKey("public.tb_users.id", ondelete="CASCADE")
        ),
        sa.Column("home_id", sa.Uuid, sa.ForeignKey("public.tb_home.id", ondelete="CASCADE")),
        sa.Column("party", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("data", sa.ARRAY(sa.Text), nullable=False),
        sa.Column("detail", sa.String(16)),
        schema="public",
    )
    op.create_index(
        "ix_tb_outbound_log_user_created", "tb_outbound_log", ["user_id", "created_at"],
        schema="public",
    )
    op.create_index(
        "ix_tb_outbound_log_home_created", "tb_outbound_log", ["home_id", "created_at"],
        schema="public",
    )
    op.create_index(
        "ix_tb_outbound_log_created", "tb_outbound_log", ["created_at"], schema="public"
    )
    op.execute("REVOKE ALL ON public.tb_consent, public.tb_outbound_log FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON public.tb_consent TO {APP}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON public.tb_outbound_log TO {APP}")
    # New accounts get no alert mail until they agree to email (R3.3); existing choices stay.
    for col in ("notify_anomaly", "notify_tier"):
        op.alter_column(
            "tb_user_preference", col, server_default=sa.false(), schema="public"
        )


def downgrade() -> None:
    for col in ("notify_anomaly", "notify_tier"):
        op.alter_column("tb_user_preference", col, server_default=sa.true(), schema="public")
    op.drop_table("tb_outbound_log", schema="public")
    op.drop_table("tb_consent", schema="public")
