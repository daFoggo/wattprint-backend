"""appliance_truth: ground-truth sub-meter watts (for accuracy)"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appliance_truth",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("house_id", sa.Integer, sa.ForeignKey("houses.id"), nullable=False),
        sa.Column("appliance", sa.String(50), nullable=False),
        sa.Column("watts", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("house_id", "appliance", "ts", name="pk_appliance_truth"),
    )
    op.execute("SELECT create_hypertable('appliance_truth', 'ts')")


def downgrade() -> None:
    op.drop_table("appliance_truth")