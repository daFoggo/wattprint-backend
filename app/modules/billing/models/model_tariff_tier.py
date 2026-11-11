from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    SmallInteger,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class TariffTier(Base):
    """A tier covers kWh in the interval (from_kwh, to_kwh]; the last tier has to_kwh NULL."""

    __tablename__ = "tb_tariff_tier"
    __table_args__ = (
        CheckConstraint("to_kwh IS NULL OR to_kwh > from_kwh", name="range"),
        {"schema": "public"},
    )

    version_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_tariff_version.id", ondelete="CASCADE"), primary_key=True
    )
    tier_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    from_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    to_kwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_per_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 2))
