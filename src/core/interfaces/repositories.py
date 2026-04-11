from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class IBaseRepository(ABC, Generic[T]):
    """Abstract base repository interface."""

    @abstractmethod
    async def get_by_id(self, entity_id: Any) -> T | None:
        """Retrieve an entity by its unique identifier."""
        ...

    @abstractmethod
    async def list(self, skip: int = 0, limit: int = 100) -> Sequence[T]:
        """Retrieve a paginated list of entities."""
        ...

    @abstractmethod
    async def add(self, entity: T) -> T:
        """Persist a new entity and return it."""
        ...

    @abstractmethod
    async def delete(self, entity_id: Any) -> bool:
        """Delete an entity by its unique identifier."""
        ...
