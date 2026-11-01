import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

_UUID_DEFAULT = text("gen_random_uuid()")
_NOW = text("now()")


class IngestBatch(Base):
    __tablename__ = "ingest_batch"
    __table_args__ = (
        CheckConstraint("status IN ('running','ok','failed')", name="status"),
        Index("ix_ingest_batch_source_started", "source", text("started_at DESC")),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    source: Mapped[str] = mapped_column(Text)
    home_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.home.id", ondelete="SET NULL"), index=True
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
    __tablename__ = "ingest_checkpoint"
    __table_args__ = {"schema": "ops"}

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("energy.series.series_id", ondelete="CASCADE"), primary_key=True, index=True
    )
    last_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
