import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class ForecastSnapshot(IdMixin, Base):
    __tablename__ = "tb_forecast_snapshot"
    __table_args__ = (
        UniqueConstraint("home_id", "generated_at", "horizon_date"),
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("public.tb_home.id", ondelete="CASCADE"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_date: Mapped[date] = mapped_column(Date)
    kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tier_cross_date: Mapped[date | None] = mapped_column(Date)
    model_version: Mapped[str] = mapped_column(Text)
    kwh_p10: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    kwh_p90: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    drivers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
