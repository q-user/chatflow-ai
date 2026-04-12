from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base


class ProjectTable(Base):
    """SQLAlchemy model for the projects table."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    bot_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bot_instances.id"), nullable=False, index=True
    )
    module_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # relationships
    company: Mapped["CompanyTable"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    user: Mapped["UserTable"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    bot_instance: Mapped["BotInstanceTable"] = relationship()  # type: ignore[name-defined]  # noqa: F821
