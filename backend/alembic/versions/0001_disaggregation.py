"""houses, aggregate_power, appliance_power (hypertables)"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "houses",
        sa.Column("id", sa.Integer, autoincrement=False, nullable=False),
        sa.Column("owner_id", sa.String, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("step_sec", sa.Integer, server_default="60", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_houses"),
    )
    op.create_index("ix_houses_owner_id", "houses", ["owner_id"])

    op.create_table(
        "aggregate_power",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("house_id", sa.Integer, sa.ForeignKey("houses.id"), nullable=False),
        sa.Column("watts", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("house_id", "ts", name="pk_aggregate_power"),
    )
    op.create_table(
        "appliance_power",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("house_id", sa.Integer, sa.ForeignKey("houses.id"), nullable=False),
        sa.Column("appliance", sa.String(50), nullable=False),
        sa.Column("watts", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("house_id", "appliance", "ts", name="pk_appliance_power"),
    )
    op.execute("SELECT create_hypertable('aggregate_power', 'ts')")
    op.execute("SELECT create_hypertable('appliance_power', 'ts')")


def downgrade() -> None:
    op.drop_table("appliance_power")
    op.drop_table("aggregate_power")
    op.drop_index("ix_houses_owner_id", table_name="houses")
    op.drop_table("houses")