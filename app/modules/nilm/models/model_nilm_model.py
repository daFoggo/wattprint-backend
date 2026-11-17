import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_model import NOW, Base, utcnow


class NilmModel(Base):
    __tablename__ = "tb_nilm_model"
    __table_args__ = (
        UniqueConstraint(
            "home_id",
            "name",
            "version",
            name="uq_tb_nilm_model_home_name_version",
            postgresql_nulls_not_distinct=True,
        ),
        # At most one active model per home, and one active shared model.
        Index(
            "uq_tb_nilm_model_active_home",
            "home_id",
            unique=True,
            postgresql_where=text("active"),
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )
    # None = the shared model for homes without one of their own.
    home_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public.tb_home.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    artifact: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )
