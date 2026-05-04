import uuid
from typing import AsyncGenerator

from fastapi import Depends
from fastapi_users import FastAPIUsers
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.auth.backend import auth_backend, auth_backend_cookie
from infrastructure.auth.manager import UserManager
from infrastructure.auth.schemas import UserCreate, UserUpdate
from infrastructure.database.models.user import UserTable
from infrastructure.database.session import get_db_session


async def get_user_db(
    session: AsyncSession = Depends(get_db_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[UserTable, uuid.UUID], None]:
    """Provide SQLAlchemyUserDatabase for fastapi-users."""
    yield SQLAlchemyUserDatabase(session, UserTable)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase[UserTable, uuid.UUID] = Depends(get_user_db),
    session: AsyncSession = Depends(get_db_session),
) -> AsyncGenerator[UserManager, None]:
    """Provide UserManager with user_db and session dependencies."""
    yield UserManager(user_db, session)


# Type aliases for schemas
UserCreateSchema = UserCreate
UserUpdateSchema = UserUpdate


# FastAPIUsers instance — регистрируем ОБА бэкенда
fastapi_users = FastAPIUsers[UserTable, uuid.UUID](
    get_user_manager,
    [auth_backend, auth_backend_cookie],
)


# Зависимость для получения активного пользователя
# Пробует оба бэкенда: Bearer (API) и Cookie (Web Dashboard)
current_active_user = fastapi_users.current_user(active=True)

current_active_user_cookie = current_active_user

current_superuser = fastapi_users.current_user(active=True, superuser=True)
