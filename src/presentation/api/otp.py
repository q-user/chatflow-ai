import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status

from core.services.otp import OTPService, RateLimitExceeded
from infrastructure.auth import current_active_user
from infrastructure.auth.otp_schemas import (
    OTPGenerateResponse,
    OTPVerifyRequest,
)
from infrastructure.config import settings
from infrastructure.database.session import get_db_session
from infrastructure.redis import redis
from infrastructure.services.messenger_link import MessengerLinkService
from sqlalchemy.ext.asyncio import AsyncSession


def get_otp_service() -> OTPService:
    """Provide OTPService using shared Redis connection pool."""
    return OTPService(redis)


async def get_messenger_link_service(
    otp_service: OTPService = Depends(get_otp_service),
    session: AsyncSession = Depends(get_db_session),
) -> MessengerLinkService:
    """Provide MessengerLinkService."""
    return MessengerLinkService(otp_service, session)


# ============================================================
# Router 1: Web cabinet — JWT-authenticated
# ============================================================
otp_web_router = APIRouter()


@otp_web_router.post(
    "/otp",
    response_model=OTPGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate OTP code (web cabinet)",
)
async def generate_otp(
    current_user=Depends(current_active_user),
    otp_service: OTPService = Depends(get_otp_service),
) -> OTPGenerateResponse:
    """Generate a 6-digit OTP code for the current authenticated user.

    Rate-limited: 1 request per minute per user.
    """
    try:
        code = await otp_service.generate_code(current_user.id)
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
        )

    return OTPGenerateResponse(code=code)


# ============================================================
# Router 2: Bot API — API key authenticated
# ============================================================
otp_bot_router = APIRouter()


def verify_bot_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """Verify the bot API key from X-API-Key header.

    Uses hmac.compare_digest for constant-time comparison (timing attack protection).
    """
    if not hmac.compare_digest(x_api_key, settings.bot_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )


@otp_bot_router.post(
    "/otp/verify",
    status_code=status.HTTP_200_OK,
    summary="Verify OTP code and link messenger (bot API)",
    dependencies=[Depends(verify_bot_api_key)],
)
async def verify_otp(
    body: OTPVerifyRequest,
    messenger_link_service: MessengerLinkService = Depends(get_messenger_link_service),
) -> dict[str, str]:
    """Verify an OTP code and link messenger ID to the user.

    Idempotent: repeated verification of the same code returns 404.
    """
    user_id = await messenger_link_service.link_by_otp(
        body.code,
        body.messenger_type,
        body.messenger_id,
    )

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired OTP code",
        )

    return {"status": "ok", "message": "Messenger linked successfully"}
