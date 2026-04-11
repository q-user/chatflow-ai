from datetime import datetime

from pydantic import UUID4, BaseModel, ConfigDict


class Company(BaseModel):
    """Domain entity representing a company (tenant)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID4 | None = None
    name: str
    created_at: datetime | None = None
