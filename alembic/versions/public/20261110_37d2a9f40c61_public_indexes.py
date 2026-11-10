"""secondary indexes for public module tables

Revision ID: 37d2a9f40c61
Revises: a7c2e9f4b1d6
"""

import sqlalchemy as sa

from alembic import op

revision = "37d2a9f40c61"
down_revision = "a7c2e9f4b1d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_public_tb_users_email", "tb_users", ["email"], schema="public", unique=True)
    op.create_index(
        "ix_public_tb_home_invite_home_id", "tb_home_invite", ["home_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_home_invite_used_by", "tb_home_invite", ["used_by"], schema="public"
    )
    op.create_index(
        "ix_public_tb_meter_home_id", "tb_meter", ["home_id"], schema="public"
    )
    op.create_index(
        "ix_meter_claim_code_hash",
        "tb_meter",
        ["claim_code_hash"],
        schema="public",
        unique=True,
        postgresql_where=sa.text("claim_code_hash IS NOT NULL"),
    )
    op.create_index("ix_public_tb_device_home_id", "tb_device", ["home_id"], schema="public")
    op.create_index(
        "ix_public_tb_device_merged_into_id", "tb_device", ["merged_into_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_device_alert_rule_device_id",
        "tb_device_alert_rule",
        ["device_id"],
        schema="public",
    )
    op.create_index(
        "ix_public_tb_series_device_id", "tb_series", ["device_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_series_meter_id", "tb_series", ["meter_id"], schema="public"
    )
    op.create_index(
        "ix_series_meter_channel",
        "tb_series",
        ["meter_id", "source_channel"],
        schema="public",
        unique=True,
        postgresql_where=sa.text("meter_id IS NOT NULL AND source_channel IS NOT NULL"),
    )
    op.create_index(
        "ix_public_tb_inference_run_home_id", "tb_inference_run", ["home_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_tariff_version_plan_code",
        "tb_tariff_version",
        ["plan_code"],
        schema="public",
    )
    op.create_index("ix_public_tb_bill_home_id", "tb_bill", ["home_id"], schema="public")
    op.create_index("ix_public_tb_bill_version_id", "tb_bill", ["version_id"], schema="public")
    op.create_index(
        "ix_public_tb_bill_item_bill_id", "tb_bill_item", ["bill_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_bill_item_device_id", "tb_bill_item", ["device_id"], schema="public"
    )
    op.create_index(
        "ix_device_cycle_home_start",
        "tb_device_cycle",
        ["home_id", sa.text("start_ts DESC")],
        schema="public",
    )
    op.create_index(
        "ix_alert_home_ts",
        "tb_alert",
        ["home_id", sa.text("ts DESC")],
        schema="public",
    )
    op.create_index("ix_public_tb_alert_device_id", "tb_alert", ["device_id"], schema="public")
    op.create_index(
        "ix_public_tb_suggestion_home_id", "tb_suggestion", ["home_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_suggestion_device_id", "tb_suggestion", ["device_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_suggestion_alert_id", "tb_suggestion", ["alert_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_suggestion_feedback_suggestion_id",
        "tb_suggestion_feedback",
        ["suggestion_id"],
        schema="public",
    )
    op.create_index(
        "ix_public_tb_suggestion_feedback_user_id",
        "tb_suggestion_feedback",
        ["user_id"],
        schema="public",
    )
    op.create_index(
        "ix_chunk_tsv", "tb_chunk", ["tsv"], schema="public", postgresql_using="gin"
    )
    op.create_index(
        "ix_chunk_embedding",
        "tb_chunk",
        ["embedding"],
        schema="public",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )
    op.create_index(
        "ix_public_tb_ingest_batch_home_id", "tb_ingest_batch", ["home_id"], schema="public"
    )
    op.create_index(
        "ix_ingest_batch_source_started",
        "tb_ingest_batch",
        ["source", sa.text("started_at DESC")],
        schema="public",
    )
    op.create_index(
        "ix_public_tb_ingest_checkpoint_series_id",
        "tb_ingest_checkpoint",
        ["series_id"],
        schema="public",
    )
    op.create_index(
        "ix_public_tb_scope_token_home_id", "tb_scope_token", ["home_id"], schema="public"
    )
    op.create_index(
        "ix_public_tb_scope_token_expires_at", "tb_scope_token", ["expires_at"], schema="public"
    )


def downgrade() -> None:
    for name, table in (
        ("ix_public_tb_scope_token_expires_at", "tb_scope_token"),
        ("ix_public_tb_scope_token_home_id", "tb_scope_token"),
        ("ix_public_tb_ingest_checkpoint_series_id", "tb_ingest_checkpoint"),
        ("ix_ingest_batch_source_started", "tb_ingest_batch"),
        ("ix_public_tb_ingest_batch_home_id", "tb_ingest_batch"),
        ("ix_chunk_embedding", "tb_chunk"),
        ("ix_chunk_tsv", "tb_chunk"),
        ("ix_public_tb_suggestion_feedback_user_id", "tb_suggestion_feedback"),
        ("ix_public_tb_suggestion_feedback_suggestion_id", "tb_suggestion_feedback"),
        ("ix_public_tb_suggestion_alert_id", "tb_suggestion"),
        ("ix_public_tb_suggestion_device_id", "tb_suggestion"),
        ("ix_public_tb_suggestion_home_id", "tb_suggestion"),
        ("ix_public_tb_alert_device_id", "tb_alert"),
        ("ix_alert_home_ts", "tb_alert"),
        ("ix_device_cycle_home_start", "tb_device_cycle"),
        ("ix_public_tb_bill_item_device_id", "tb_bill_item"),
        ("ix_public_tb_bill_item_bill_id", "tb_bill_item"),
        ("ix_public_tb_bill_version_id", "tb_bill"),
        ("ix_public_tb_bill_home_id", "tb_bill"),
        ("ix_public_tb_tariff_version_plan_code", "tb_tariff_version"),
        ("ix_public_tb_inference_run_home_id", "tb_inference_run"),
        ("ix_series_meter_channel", "tb_series"),
        ("ix_public_tb_series_meter_id", "tb_series"),
        ("ix_public_tb_series_device_id", "tb_series"),
        ("ix_public_tb_device_alert_rule_device_id", "tb_device_alert_rule"),
        ("ix_public_tb_device_merged_into_id", "tb_device"),
        ("ix_public_tb_device_home_id", "tb_device"),
        ("ix_meter_claim_code_hash", "tb_meter"),
        ("ix_public_tb_meter_home_id", "tb_meter"),
        ("ix_public_tb_home_invite_used_by", "tb_home_invite"),
        ("ix_public_tb_home_invite_home_id", "tb_home_invite"),
        ("ix_public_tb_users_email", "tb_users"),
    ):
        op.drop_index(name, table_name=table, schema="public")
