from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

_NOW = text("now()")


class IngestBatch(Base):
    __tablename__ = "tb_ingest_batch"
    __table_args__ = (
        CheckConstraint("status IN ('running','ok','failed')", name="status"),
        Index("ix_ingest_batch_source_started", "source", text("started_at DESC")),
        {"schema": "public"},
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    home_id: Mapped[int | None] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="SET NULL"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_in: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    rows_new: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    rows_dup: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    rows_bad: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="running", server_default="running")
    note: Mapped[str | None] = mapped_column(Text)


class IngestCheckpoint(Base):
    __tablename__ = "tb_ingest_checkpoint"
    __table_args__ = {"schema": "public"}

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("public.tb_series.series_id", ondelete="CASCADE"), primary_key=True, index=True
    )
    last_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
