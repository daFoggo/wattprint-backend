"""revoke wattprint_ai reads of home energy and chat content; it keeps reference data only

Revision ID: 7ed04a4f7308
Revises: f4b8c2e6a913
"""

from alembic import op

revision = "7ed04a4f7308"
down_revision = "f4b8c2e6a913"
branch_labels = None
depends_on = None

ROLE = "wattprint_ai"
HOME_DATA = "ai.fact_reading_1m, ai.fact_estimate_1m, ai.fact_energy, ai.dim_home, ai.dim_device"
CHAT = "ai.ai_conversation, ai.ai_message, ai.ai_tool_call"


def upgrade() -> None:
    op.execute(f"REVOKE ALL ON {HOME_DATA} FROM {ROLE}")
    op.execute(f"REVOKE ALL ON {CHAT} FROM {ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT SELECT ON {HOME_DATA} TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {CHAT} TO {ROLE}")
