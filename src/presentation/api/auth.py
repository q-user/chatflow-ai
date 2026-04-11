from infrastructure.auth import auth_backend, fastapi_users
from infrastructure.auth.schemas import UserCreate, UserRead, UserUpdate

# Auth router: login/logout via JWT
# POST /auth/jwt/login, POST /auth/jwt/logout, GET /auth/jwt/me
auth_router = fastapi_users.get_auth_router(auth_backend)

# Register router: create new user
# POST /auth/register
register_router = fastapi_users.get_register_router(UserRead, UserCreate)  # type: ignore[type-var]

# Users router: CRUD operations on users
# GET/PUT/PATCH/DELETE /users/{id}
users_router = fastapi_users.get_users_router(UserRead, UserUpdate)  # type: ignore[type-var]
