import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class ExpectModel(IdMixin, Base):
    __tablename__ = "tb_expect_model"
    __table_args__ = (
        UniqueConstraint("home_id", "version"),
        Index("uq_tb_expect_model_active", "home_id", unique=True, postgresql_where=text("active")),
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
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
