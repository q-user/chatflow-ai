from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

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

app = FastAPI(title="ChatFlow AI")

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
app.include_router(auth_router_cookie, prefix="/auth", tags=["auth-cookie"])
app.include_router(register_router, prefix="/auth", tags=["auth"])
app.include_router(users_router, prefix="/users", tags=["users"])

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
