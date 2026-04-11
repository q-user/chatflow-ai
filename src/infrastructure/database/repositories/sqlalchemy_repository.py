from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from core.interfaces.repositories import IBaseRepository

ModelT = TypeVar("ModelT", bound=DeclarativeBase)
SchemaT = TypeVar("SchemaT", bound=BaseModel)


class BaseSqlAlchemyRepository(IBaseRepository[SchemaT], Generic[ModelT, SchemaT]):
    """Base SQLAlchemy repository that maps SQLAlchemy models to Pydantic schemas."""

    model_class: type[ModelT]
    schema_class: type[SchemaT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_schema(self, model: ModelT) -> SchemaT:
        """Convert a SQLAlchemy model instance to a Pydantic schema."""
        return self.schema_class.model_validate(model)

    async def get_by_id(self, entity_id: Any) -> SchemaT | None:
        result = await self._session.get(self.model_class, entity_id)
        if result is None:
            return None
        return self._to_schema(result)

    async def list(self, skip: int = 0, limit: int = 100) -> Sequence[SchemaT]:
        stmt = select(self.model_class).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [self._to_schema(m) for m in models]

    async def add(self, entity: SchemaT) -> SchemaT:
        model = self.model_class(**entity.model_dump(exclude={"id"}))
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_schema(model)

    async def delete(self, entity_id: Any) -> bool:
        result = await self._session.get(self.model_class, entity_id)
        if result is None:
            return False
        await self._session.delete(result)
        return True
