from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import Base

# A cohort smaller than this is never published (percentiles of a handful of homes identify
# them). Mirrored by the `ck_cohort_stat_min_size` CHECK in the database.
MIN_COHORT_HOMES = 10


class CohortStat(Base):
    __tablename__ = "tb_cohort_stat"
    __table_args__ = (
        CheckConstraint(f"n_homes >= {MIN_COHORT_HOMES}", name="min_size"),
        {"schema": "public"},
    )

    cohort_key: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    p10_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    p33_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    p66_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    p90_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    n_homes: Mapped[int] = mapped_column(Integer)
