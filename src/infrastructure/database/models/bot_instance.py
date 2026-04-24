from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON as GenericJSON

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from .company import CompanyTable


class BotInstanceTable(Base):
    """SQLAlchemy model for bot instances (messenger integrations)."""

    __tablename__ = "bot_instances"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    messenger_type: Mapped[str] = mapped_column(String(10), nullable=False)  # TG / YM
    token: Mapped[str] = mapped_column(String(512), nullable=False)  # bot API token
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # active / inactive
    module_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="finance"
    )  # finance, estimator, hr, etc.
    config: Mapped[dict | None] = mapped_column(
        GenericJSON, nullable=True
    )  # {"system_prompt": "...", "output_format": "csv", ...}

    __table_args__ = (
        CheckConstraint(
            "messenger_type IN ('TG', 'YM')", name="ck_bot_instances_messenger_type"
        ),
    )

    # relationships
    company: Mapped["CompanyTable"] = relationship(back_populates="bots")
