import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base


class InferenceRun(Base):
    __tablename__ = "tb_inference_run"
    __table_args__ = (
        CheckConstraint("status IN ('running','ok','failed')", name="status"),
        {"schema": "public"},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE"), index=True
    )
    model_name: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(Text)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="running", server_default="running")
