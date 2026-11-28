import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin

ALERT_KINDS = (
    "longer_than_usual",
    "standby_high",
    "tier_near",
    "unexplained_load",
    "watch_hit",
    "watch_broken",
    "device_on",
    "device_off",
    "device_long_run",
    "device_high_power",
    "usage_anomaly",
    "device_anomaly",
)


class Alert(IdMixin, Base):
    __tablename__ = "tb_alert"
    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','critical')", name="severity"),
        CheckConstraint("status IN ('open','acknowledged','resolved')", name="status"),
        CheckConstraint(f"kind IN ({', '.join(repr(k) for k in ALERT_KINDS)})", name="kind"),
        Index("ix_alert_home_ts", "home_id", text("ts DESC")),
        # A detector upserts on (home, dedup_key) while its alert is not resolved.
        Index(
            "uq_tb_alert_home_dedup_unresolved",
            "home_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
        ),
        {"schema": "public"},
    )

    # Random, not UUIDv7: a v7 id carries its creation time to the millisecond, which a member
    # who sees days only (and a daily copilot token) must not read off the alert (D9-1).
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    dedup_key: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
