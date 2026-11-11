from sqlalchemy import (
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class TariffPlan(Base):
    __tablename__ = "tb_tariff_plan"
    __table_args__ = {"schema": "public"}

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, default="VND", server_default="VND")
