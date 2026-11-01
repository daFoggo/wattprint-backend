import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    REAL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

_NOW = text("now()")


class Series(Base):
    __tablename__ = "series"
    __table_args__ = (
        CheckConstraint("kind IN ('main','plug','device')", name="kind"),
        CheckConstraint("kind <> 'main' OR device_id IS NULL", name="main_has_no_device"),
        CheckConstraint(
            "kind NOT IN ('plug','device') OR device_id IS NOT NULL",
            name="device_kinds_need_device",
        ),
        UniqueConstraint(
            "home_id", "kind", "device_id", "metric",
            name="uq_series_home_kind_device_metric",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_series_meter_channel",
            "meter_id",
            "source_channel",
            unique=True,
            postgresql_where=text("meter_id IS NOT NULL AND source_channel IS NOT NULL"),
        ),
        {"schema": "energy"},
    )

    series_id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.home.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.device.id", ondelete="CASCADE"), index=True
    )
    meter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.meter.id", ondelete="SET NULL")
    )
    source_channel: Mapped[str | None] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(ForeignKey("catalog.metric.event_type"))
    unit: Mapped[str] = mapped_column(Text)


class InferenceRun(Base):
    __tablename__ = "inference_run"
    __table_args__ = (
        CheckConstraint("status IN ('running','ok','failed')", name="status"),
        {"schema": "energy"},
    )

    run_id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.home.id", ondelete="CASCADE"), index=True
    )
    model_name: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(Text)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="running", server_default="running")


class WeatherHourly(Base):
    __tablename__ = "weather_hourly"
    __table_args__ = {"schema": "energy"}

    province_code: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    temp_c: Mapped[float | None] = mapped_column(REAL)
    humidity_pct: Mapped[float | None] = mapped_column(REAL)


# Hypertables: Core inserts only, no ORM classes. No FKs by design (see spec section 5).
reading_table = sa.Table(
    "reading",
    Base.metadata,
    sa.Column("ts", DateTime(timezone=True), nullable=False, primary_key=True),
    sa.Column("series_id", Integer, nullable=False, primary_key=True),
    sa.Column("value", REAL, nullable=False),
    sa.Column("quality", SmallInteger, nullable=False, server_default="0"),
    schema="energy",
)

device_estimate_table = sa.Table(
    "device_estimate",
    Base.metadata,
    sa.Column("ts", DateTime(timezone=True), nullable=False, primary_key=True),
    sa.Column("series_id", Integer, nullable=False, primary_key=True),
    sa.Column("value", REAL, nullable=False),
    sa.Column("run_id", Integer),
    schema="energy",
)
