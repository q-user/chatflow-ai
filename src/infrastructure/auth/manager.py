import uuid
from typing import Any

from fastapi import Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.auth.schemas import UserCreate
from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable
from infrastructure.config import settings


class UserManager(UUIDIDMixin, BaseUserManager[UserTable, uuid.UUID]):
    """User manager with atomic Company + User creation.

    Since company_id is NOT NULL on users table, we must create a Company
    before inserting the User. This override handles that in a single
    transactional flow.
    """

    reset_password_token_secret = settings.secret_key
    verification_token_secret = settings.secret_key

    def __init__(self, user_db: Any, session: AsyncSession) -> None:
        super().__init__(user_db)
        self._session = session

    async def create(  # type: ignore[override]
        self,
        user_create: UserCreate,
        safe: bool = False,
        request: Request | None = None,
    ) -> UserTable:
        """Override: Create Company + User atomically.

        If user_create doesn't have company_id, we create a default Company
        and inject its ID into the user_create before calling super().create().
        """
        company_id = user_create.company_id

        if not company_id:
            # Создаём компанию «на лету» в рамках той же сессии
            company_name = (
                user_create.company_name or f"Company-{user_create.email.split('@')[0]}"
            )

            company = CompanyTable(name=company_name)
            self._session.add(company)
            await self._session.flush()
            company_id = company.id  # type: ignore[assignment]

            # Пересоздаём UserCreate с company_id — иммутабельный подход
            # (мутация Pydantic-модели ненадёжна для create_update_dict)
            user_create = UserCreate(
                email=user_create.email,
                password=user_create.password,
                company_id=company_id,  # ty: ignore[invalid-argument-type]
                company_name=user_create.company_name,
                is_active=user_create.is_active,
                is_superuser=user_create.is_superuser,
                is_verified=user_create.is_verified,
            )

        return await super().create(user_create, safe, request)
