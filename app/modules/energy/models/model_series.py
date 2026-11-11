import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class Series(Base):
    __tablename__ = "tb_series"
    __table_args__ = (
        CheckConstraint("kind IN ('main','plug','device')", name="kind"),
        CheckConstraint("kind <> 'main' OR device_id IS NULL", name="main_has_no_device"),
        CheckConstraint(
            "kind NOT IN ('plug','device') OR device_id IS NOT NULL",
            name="device_kinds_need_device",
        ),
        UniqueConstraint(
            "home_id",
            "kind",
            "device_id",
            "metric",
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
        {"schema": "public"},
    )

    series_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="CASCADE"), index=True
    )
    meter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_meter.id", ondelete="SET NULL"), index=True
    )
    source_channel: Mapped[str | None] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(64), ForeignKey("public.cat_metric.event_type"))
    unit: Mapped[str] = mapped_column(Text)
