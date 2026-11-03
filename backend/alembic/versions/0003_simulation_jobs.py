"""simulation_jobs: background replay of one REFIT day"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_jobs",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column("house_id", sa.Integer, sa.ForeignKey("houses.id"), nullable=False),
        sa.Column("owner_id", sa.String, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rows_per_second", sa.Float, nullable=False),
        sa.Column("total_minutes", sa.Integer, nullable=True),
        sa.Column("done_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_jobs"),
    )
    op.create_index("ix_simulation_jobs_house_id", "simulation_jobs", ["house_id"])


def downgrade() -> None:
    op.drop_index("ix_simulation_jobs_house_id", table_name="simulation_jobs")
    op.drop_table("simulation_jobs")