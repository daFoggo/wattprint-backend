from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class Province(Base):
    __tablename__ = "cat_province"
    __table_args__ = {"schema": "public"}

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    lat: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    lon: Mapped[Decimal] = mapped_column(Numeric(8, 5))
