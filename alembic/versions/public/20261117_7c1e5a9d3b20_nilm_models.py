"""nilm module: model registry per home, failure note on inference runs

Revision ID: 7c1e5a9d3b20
Revises: 5d0c9a3e7f21
"""

import sqlalchemy as sa

from alembic import op

revision = "7c1e5a9d3b20"
down_revision = "5d0c9a3e7f21"
branch_labels = None
depends_on = None

APP = "wattprint_app"
INGEST = "wattprint_ingest"
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "tb_nilm_model",
        sa.Column("id", sa.Uuid, server_default=sa.text("uuidv7()"), primary_key=True),
        # NULL = the shared model, used by every home without a model of its own.
        sa.Column("home_id", sa.Uuid),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        # Bundle path relative to the NILM model directory (settings.nilm_model_dir).
        sa.Column("artifact", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(
            ["home_id"],
            ["public.tb_home.id"],
            name="fk_tb_nilm_model_home_id_tb_home",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "home_id",
            "name",
            "version",
            name="uq_tb_nilm_model_home_name_version",
            postgresql_nulls_not_distinct=True,
        ),
        schema="public",
    )
    # At most one active model per home, and one active shared model.
    op.execute(
        "CREATE UNIQUE INDEX uq_tb_nilm_model_active_home ON public.tb_nilm_model (home_id) "
        "NULLS NOT DISTINCT WHERE active"
    )
    op.execute(
        "COMMENT ON TABLE public.tb_nilm_model IS 'NILM model bundles. A home uses its own "
        "active model, else the active shared one (home_id NULL). Changing a home''s model means "
        "rewinding its nilm checkpoint so the newest run wins.'"
    )
    op.add_column("tb_inference_run", sa.Column("error", sa.Text), schema="public")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.tb_nilm_model TO {APP}")
    op.execute(f"GRANT SELECT ON public.tb_nilm_model TO {INGEST}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON public.tb_nilm_model FROM {APP}, {INGEST}")
    op.drop_column("tb_inference_run", "error", schema="public")
    op.drop_table("tb_nilm_model", schema="public")
