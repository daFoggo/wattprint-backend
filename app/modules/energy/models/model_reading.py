import sqlalchemy as sa
from sqlalchemy import (
    REAL,
    DateTime,
    Integer,
    SmallInteger,
)

from app.common.base_model import Base

# Hypertables: Core inserts only, no ORM classes. No FKs by design (see spec section 5).
reading_table = sa.Table(
    "tb_reading",
    Base.metadata,
    sa.Column("ts", DateTime(timezone=True), nullable=False, primary_key=True),
    sa.Column("series_id", Integer, nullable=False, primary_key=True),
    sa.Column("value", REAL, nullable=False),
    sa.Column("quality", SmallInteger, nullable=False, server_default="0"),
    schema="public",
)
