from datetime import UTC, datetime

from sqlalchemy import DateTime, Identity, Integer, MetaData, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

NOW = text("now()")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    # Business tables live in "public".
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)


class CreatedAtMixin:
    # Python default too: an expired attribute cannot lazy-load under asyncio.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=NOW
    )


class BaseModel(IdMixin, CreatedAtMixin, Base):
    __abstract__ = True
