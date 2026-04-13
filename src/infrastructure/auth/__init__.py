from infrastructure.auth.backend import auth_backend, auth_backend_cookie  # noqa: F401
from infrastructure.auth.dependencies import (  # noqa: F401
    UserCreateSchema,
    UserUpdateSchema,
    current_active_user,
    current_active_user_cookie,
    fastapi_users,
)
from infrastructure.auth.manager import UserManager  # noqa: F401
from infrastructure.auth.schemas import UserCreate, UserRead, UserUpdate  # noqa: F401

__all__ = [
    "auth_backend",
    "auth_backend_cookie",
    "fastapi_users",
    "current_active_user",
    "current_active_user_cookie",
    "UserManager",
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "UserCreateSchema",
    "UserUpdateSchema",
]
