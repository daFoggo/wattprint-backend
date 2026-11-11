from sqlalchemy import (
    CheckConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base


class Metric(Base):
    __tablename__ = "cat_metric"
    __table_args__ = (
        CheckConstraint("aggregation IN ('mean','max','energy')", name="aggregation"),
        {"schema": "public"},
    )

    event_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    unit: Mapped[str] = mapped_column(String(16))
    aggregation: Mapped[str] = mapped_column(String(16))
