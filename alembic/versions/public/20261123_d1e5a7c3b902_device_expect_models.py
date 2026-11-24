"""tb_expect_model.device_id: an expected-usage model per device beside the home's (NULL)

Revision ID: d1e5a7c3b902
Revises: c4d7f19e2a60
"""

import sqlalchemy as sa

from alembic import op

revision = "d1e5a7c3b902"
down_revision = "c4d7f19e2a60"
branch_labels = None
depends_on = None

NONE = "'00000000-0000-0000-0000-000000000000'::uuid"  # the home's own model in the indexes


def upgrade() -> None:
    op.add_column(
        "tb_expect_model",
        sa.Column("device_id", sa.Uuid, sa.ForeignKey("public.tb_device.id", ondelete="CASCADE")),
        schema="public",
    )
    op.drop_constraint(op.f("uq_tb_expect_model_home_version"), "tb_expect_model", schema="public")
    op.execute("DROP INDEX public.uq_tb_expect_model_active")
    op.execute(
        "CREATE UNIQUE INDEX uq_tb_expect_model_owner_version ON public.tb_expect_model "
        f"(home_id, COALESCE(device_id, {NONE}), version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tb_expect_model_active ON public.tb_expect_model "
        f"(home_id, COALESCE(device_id, {NONE})) WHERE active"
    )


def downgrade() -> None:
    op.execute("DELETE FROM public.tb_expect_model WHERE device_id IS NOT NULL")
    op.execute("DROP INDEX public.uq_tb_expect_model_active")
    op.execute("DROP INDEX public.uq_tb_expect_model_owner_version")
    op.create_unique_constraint(
        op.f("uq_tb_expect_model_home_version"),
        "tb_expect_model",
        ["home_id", "version"],
        schema="public",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tb_expect_model_active ON public.tb_expect_model (home_id) "
        "WHERE active"
    )
    op.drop_column("tb_expect_model", "device_id", schema="public")
