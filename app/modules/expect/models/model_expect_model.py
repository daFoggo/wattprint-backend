import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, Boolean, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class ExpectModel(IdMixin, Base):
    __tablename__ = "tb_expect_model"
    __table_args__ = (
        # Unique per owner (the home, or one of its devices) and version, one active per owner:
        # COALESCE indexes in the migration (d1e5a7c3b902).
        Index(
            "uq_tb_expect_model_owner_version",
            "home_id",
            text("COALESCE(device_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "version",
            unique=True,
        ),
        Index(
            "uq_tb_expect_model_active",
            "home_id",
            text("COALESCE(device_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
            postgresql_where=text("active"),
        ),
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="CASCADE")
    )
    version: Mapped[str] = mapped_column(Text)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    features: Mapped[list[str]] = mapped_column(ARRAY(Text))
    boosters: Mapped[dict[str, str]] = mapped_column(JSONB)
    residuals: Mapped[list[float]] = mapped_column(ARRAY(REAL))
    widen: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
