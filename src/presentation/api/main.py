from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration

from infrastructure.config import settings
from infrastructure.auth import current_superuser
from infrastructure.database.session import lifespan_db
from presentation.api.auth import (
    auth_router,
    auth_router_cookie,
    register_router,
    users_router,
)
from presentation.api.hooks import hooks_router
from presentation.api.otp import otp_bot_router, otp_web_router
from presentation.web.middleware import HtmxAuthMiddleware
from presentation.web.pages import router as web_router

app = FastAPI(title="ChatFlow AI", lifespan=lifespan_db)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        integrations=[
            FastApiIntegration(),
            CeleryIntegration(),
            HttpxIntegration(),
        ],
    )

# Middleware: HTMX auth redirect
app.add_middleware(HtmxAuthMiddleware)


# 401 exception handler: redirect browser to /login, API gets JSON
@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse(url="/login", status_code=303)
    return JSONResponse({"detail": "Not authenticated"}, status_code=401)


# Include auth routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(auth_router_cookie, prefix="/auth/cookie", tags=["auth-cookie"])
app.include_router(register_router, prefix="/auth", tags=["auth"])
app.include_router(
    users_router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(current_superuser)],
)

# Include OTP routers
app.include_router(otp_web_router, prefix="/auth", tags=["otp"])
app.include_router(otp_bot_router, prefix="/auth", tags=["otp-bot"])

# Include webhook router for messengers
app.include_router(hooks_router, tags=["webhooks"])

# Web Dashboard (Jinja2 + HTMX)
app.include_router(web_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
