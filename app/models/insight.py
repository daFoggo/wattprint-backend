import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    REAL,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

_UUID_DEFAULT = text("gen_random_uuid()")

# A cohort smaller than this is never published (percentiles of a handful of homes identify
# them). Mirrored by the `ck_cohort_stat_min_size` CHECK in the database.
MIN_COHORT_HOMES = 10


class DeviceCycle(Base):
    """One on/off cycle of a device. Hypertable on start_ts (30-day chunks)."""

    __tablename__ = "device_cycle"
    __table_args__ = (
        CheckConstraint("end_ts > start_ts", name="range"),
        Index("ix_device_cycle_home_start", "home_id", text("start_ts DESC")),
        {"schema": "insight"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.device.id", ondelete="CASCADE"), primary_key=True
    )
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    energy_wh: Mapped[float] = mapped_column(Float)
    peak_w: Mapped[float] = mapped_column(REAL)


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','critical')", name="severity"),
        CheckConstraint("status IN ('open','acknowledged','resolved')", name="status"),
        Index("ix_alert_home_ts", "home_id", text("ts DESC")),
        {"schema": "insight"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.device.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")


class ForecastSnapshot(Base):
    __tablename__ = "forecast_snapshot"
    __table_args__ = (
        UniqueConstraint("home_id", "generated_at", "horizon_date"),
        {"schema": "insight"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_date: Mapped[date] = mapped_column(Date)
    kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tier_cross_date: Mapped[date | None] = mapped_column(Date)
    model_version: Mapped[str] = mapped_column(Text)


class CohortStat(Base):
    __tablename__ = "cohort_stat"
    __table_args__ = (
        CheckConstraint(f"n_homes >= {MIN_COHORT_HOMES}", name="min_size"),
        {"schema": "insight"},
    )

    cohort_key: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    p10_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    p33_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    p66_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    p90_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    n_homes: Mapped[int] = mapped_column(Integer)
