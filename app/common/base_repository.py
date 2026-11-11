from abc import ABC
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from .base_model import Base
from .exceptions import NotFoundError

MAX_LIMIT = 500


class BaseRepository[ModelT: Base](ABC):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        if not isinstance(getattr(type(self), "model", None), type):
            raise TypeError(f"{type(self).__name__} must set `model = <ORM class>`")
        self.session = session

    # ---- helpers -------------------------------------------------------------------------------

    def _where(
        self, where: Iterable[ColumnElement[bool]], filters: Mapping[str, Any]
    ) -> list[ColumnElement[bool]]:
        clauses = list(where)
        for name, value in filters.items():
            column = getattr(self.model, name, None)
            if not isinstance(column, InstrumentedAttribute):
                raise ValueError(f"{self.model.__name__} has no column {name!r}")
            clauses.append(column.is_(None) if value is None else column == value)
        return clauses

    def _not_found(self, ident: Any) -> NotFoundError:
        return NotFoundError(f"{self.model.__name__} {ident!r} not found")

    # ---- create --------------------------------------------------------------------------------

    async def create(self, **data: Any) -> ModelT:
        instance = self.model(**data)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def create_many(self, rows: Iterable[Mapping[str, Any]]) -> list[ModelT]:
        instances = [self.model(**row) for row in rows]
        self.session.add_all(instances)
        await self.session.flush()
        return instances

    # ---- read ----------------------------------------------------------------------------------

    async def read_by_id(self, ident: Any) -> ModelT | None:
        """``ident`` is the primary key value, or a tuple for a composite key."""
        return await self.session.get(self.model, ident)

    async def read_by_id_or_fail(self, ident: Any) -> ModelT:
        instance = await self.read_by_id(ident)
        if instance is None:
            raise self._not_found(ident)
        return instance

    async def read_one(self, *where: ColumnElement[bool], **filters: Any) -> ModelT | None:
        stmt = select(self.model).where(*self._where(where, filters)).limit(2)
        rows = (await self.session.scalars(stmt)).all()
        if len(rows) > 1:
            raise ValueError(f"read_one matched several {self.model.__name__} rows")
        return rows[0] if rows else None

    async def read_many(
        self,
        *where: ColumnElement[bool],
        order_by: Sequence[Any] | None = None,
        offset: int = 0,
        limit: int | None = 100,
        **filters: Any,
    ) -> list[ModelT]:
        stmt = select(self.model).where(*self._where(where, filters))
        if order_by:
            stmt = stmt.order_by(*order_by)
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(min(limit, MAX_LIMIT))
        return list((await self.session.scalars(stmt)).all())

    async def read_count(self, *where: ColumnElement[bool], **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model).where(*self._where(where, filters))
        return int(await self.session.scalar(stmt) or 0)

    async def read_exists(self, *where: ColumnElement[bool], **filters: Any) -> bool:
        stmt = select(self.model).where(*self._where(where, filters)).exists()
        return bool(await self.session.scalar(select(stmt)))

    # ---- update --------------------------------------------------------------------------------

    async def update(self, instance: ModelT, **data: Any) -> ModelT:
        for name, value in data.items():
            if not isinstance(getattr(self.model, name, None), InstrumentedAttribute):
                raise ValueError(f"{self.model.__name__} has no column {name!r}")
            setattr(instance, name, value)
        await self.session.flush()
        return instance

    async def update_by_id(self, ident: Any, **data: Any) -> ModelT:
        return await self.update(await self.read_by_id_or_fail(ident), **data)

    # ---- delete --------------------------------------------------------------------------------

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def delete_by_id(self, ident: Any) -> bool:
        """True when a row was deleted, False when there was none."""
        instance = await self.read_by_id(ident)
        if instance is None:
            return False
        await self.delete(instance)
        return True
