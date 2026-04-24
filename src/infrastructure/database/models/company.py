from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base


class CompanyTable(Base):
    """SQLAlchemy model for the companies table."""

    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    allowed_modules: Mapped[list[str]] = mapped_column(
        JSONB, server_default='["finance"]', nullable=False, default=lambda: ["finance"]
    )

    # relationships
    users: Mapped[list["UserTable"]] = relationship(back_populates="company")
    bots: Mapped[list["BotInstanceTable"]] = relationship(back_populates="company")
