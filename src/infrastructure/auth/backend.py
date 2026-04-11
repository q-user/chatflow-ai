from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy

from infrastructure.config import settings

# Bearer token transport — логин по email/password
# tokenUrl is relative to the auth router prefix (/auth)
bearer_transport = BearerTransport(tokenUrl="/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    """Create JWT strategy with secret from settings."""
    return JWTStrategy(secret=settings.secret_key, lifetime_seconds=3600)


# Authentication backend — единая точка входа для JWT
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
