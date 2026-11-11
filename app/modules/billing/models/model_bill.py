import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base, IdMixin


class Bill(IdMixin, Base):
    __tablename__ = "tb_bill"
    __table_args__ = (
        CheckConstraint("status IN ('open','partial','closed')", name="status"),
        UniqueConstraint("home_id", "period_start"),
        {"schema": "public"},
    )

    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_tariff_version.id"), index=True
    )
    kwh_total: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    amount_before_vat: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    coverage: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    tariff_straddle: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String(16))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
