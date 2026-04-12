"""Domain entity: result of data package processing."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Project(BaseModel):
    """Domain entity representing a processing project."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    company_id: UUID
    user_id: UUID
    bot_instance_id: UUID
    module_type: str
    status: str = "pending"  # pending / processing / completed / failed
    input_data: dict[str, Any] | None = None  # snapshot from SessionService
    result_data: dict[str, Any] | None = None  # processing result
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
