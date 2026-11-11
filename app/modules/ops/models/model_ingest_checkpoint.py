import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base


class IngestCheckpoint(Base):
    __tablename__ = "tb_ingest_checkpoint"
    __table_args__ = {"schema": "public"}

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_series.series_id", ondelete="CASCADE"), primary_key=True, index=True
    )
    last_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
