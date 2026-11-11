import sqlalchemy as sa
from sqlalchemy import (
    REAL,
    DateTime,
    Integer,
)

from app.common.base_model import Base

device_estimate_table = sa.Table(
    "tb_device_estimate",
    Base.metadata,
    sa.Column("ts", DateTime(timezone=True), nullable=False, primary_key=True),
    sa.Column("series_id", Integer, nullable=False, primary_key=True),
    sa.Column("value", REAL, nullable=False),
    sa.Column("run_id", Integer),
    schema="public",
)
