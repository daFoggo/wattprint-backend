from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class TariffVersion(IdMixin, Base):
    __tablename__ = "tb_tariff_version"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_range"),
        UniqueConstraint("plan_code", "valid_from"),
        {"schema": "public"},
    )

    plan_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("public.tb_tariff_plan.code"), index=True
    )
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    source_doc: Mapped[str] = mapped_column(Text)
