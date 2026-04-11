from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from fastapi_users.db import SQLAlchemyBaseUserTableUUID

from infrastructure.database.base import Base


class UserTable(SQLAlchemyBaseUserTableUUID, Base):
    """SQLAlchemy model for the users table with fastapi-users integration."""

    __tablename__ = "users"

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    telegram_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    yandex_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )

    # relationships
    company: Mapped["CompanyTable"] = relationship(back_populates="users")  # type: ignore[name-defined]  # noqa: F821
