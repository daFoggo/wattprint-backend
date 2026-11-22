import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base, IdMixin, utcnow

WATCH_METRICS = (
    "bill_vnd",
    "bill_kwh",
    "forecast_vnd",
    "today_kwh",
    "power_w",
    "device_kwh_today",
    "sql",
    "device_on",
    "device_off",
    "device_run_min",
    "device_power_w",
)
DEVICE_RUNS = ("device_on", "device_off", "device_run_min", "device_power_w")  # once per run
WATCH_STATUSES = ("active", "fired", "expired", "cancelled", "broken")


class Watch(IdMixin, Base):
    """A threshold the user asked Wappi to watch; the insight worker checks it every `every_s`."""

    __tablename__ = "tb_watch"
    __table_args__ = (
        CheckConstraint(f"metric IN ({', '.join(repr(m) for m in WATCH_METRICS)})", name="metric"),
        CheckConstraint("op IN ('gt', 'lt')", name="op"),
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in WATCH_STATUSES)})", name="status"),
        CheckConstraint("every_s >= 60", name="every"),
        CheckConstraint("(metric = 'sql') = (sql_text IS NOT NULL)", name="sql"),
        CheckConstraint("(metric LIKE 'device_%') = (device_id IS NOT NULL)", name="device"),
        Index("ix_tb_watch_due", "next_check_at", postgresql_where=text("status = 'active'")),
        Index("ix_tb_watch_home_user", "home_id", "user_id"),
        {"schema": "public"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_users.id", ondelete="CASCADE"))
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    sql_text: Mapped[str | None] = mapped_column(Text)
    op: Mapped[str] = mapped_column(String(2))
    threshold: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(Text, default="", server_default="")
    every_s: Mapped[int] = mapped_column(Integer)
    # Fires once per day, cycle or device run instead of once; rows from before default to once.
    repeat: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    last_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fails: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    utterance: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )
