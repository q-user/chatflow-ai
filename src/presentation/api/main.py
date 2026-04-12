from fastapi import FastAPI

from presentation.api.auth import auth_router, register_router, users_router
from presentation.api.hooks import hooks_router
from presentation.api.otp import otp_bot_router, otp_web_router

app = FastAPI(title="ChatFlow AI")

# Include auth routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(register_router, prefix="/auth", tags=["auth"])
app.include_router(users_router, prefix="/users", tags=["users"])

# Include OTP routers
app.include_router(otp_web_router, prefix="/auth", tags=["otp"])
app.include_router(otp_bot_router, prefix="/auth", tags=["otp-bot"])

# Include webhook router for messengers
app.include_router(hooks_router, tags=["webhooks"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
