import uuid
from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Numeric,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base, IdMixin


class BillItem(IdMixin, Base):
    __tablename__ = "tb_bill_item"
    __table_args__ = {"schema": "public"}

    bill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_bill.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_device.id", ondelete="SET NULL"), index=True
    )
    label: Mapped[str] = mapped_column(Text)
    kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    share: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
