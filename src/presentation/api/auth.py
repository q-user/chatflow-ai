from infrastructure.auth import auth_backend, auth_backend_cookie, fastapi_users
from infrastructure.auth.schemas import UserCreate, UserRead, UserUpdate

# Auth router: login/logout via JWT (Bearer)
# POST /auth/jwt/login, POST /auth/jwt/logout, GET /auth/jwt/me
auth_router = fastapi_users.get_auth_router(auth_backend)

# Cookie auth router: login/logout via cookies (Web Dashboard)
# POST /auth/cookie/login, POST /auth/cookie/logout, GET /auth/cookie/me
auth_router_cookie = fastapi_users.get_auth_router(auth_backend_cookie)

# Register router: create new user
# POST /auth/register
register_router = fastapi_users.get_register_router(UserRead, UserCreate)

# Users router: CRUD operations on users
# GET/PUT/PATCH/DELETE /users/{id}
users_router = fastapi_users.get_users_router(UserRead, UserUpdate)
