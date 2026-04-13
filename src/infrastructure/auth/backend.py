from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)

from infrastructure.config import settings

# ── Bearer transport (API clients) ──
bearer_transport = BearerTransport(tokenUrl="/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    """Create JWT strategy with secret from settings."""
    return JWTStrategy(secret=settings.secret_key, lifetime_seconds=3600)


# Bearer auth backend — для API-клиентов (существующий)
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# ── Cookie transport (Web Dashboard) ──
cookie_transport = CookieTransport(
    cookie_max_age=3600,  # 1 час — совпадает с JWT lifetime
    cookie_secure=settings.environment == "production",  # HTTPS только в prod
    cookie_httponly=True,  # Недоступен из JS (XSS protection)
    cookie_samesite="lax",  # Защита от CSRF (lax — позволяет навигацию)
    cookie_name="cfai_at",  # Имя куки — короткое, уникальное
)


# Cookie auth backend — для Web Dashboard (браузер)
auth_backend_cookie = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,  # та же стратегия, что и Bearer
)
