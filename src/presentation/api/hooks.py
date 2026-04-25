"""Dynamic webhook router for messenger webhooks.

Single entry point: POST /api/v1/hooks/{messenger_type}/{bot_uuid}
Routes to the correct adapter, parses payload, and dispatches to session FSM.
"""

import uuid

from fastapi import APIRouter, Depends, Header, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.otp import OTPService
from core.services.session import SessionService
from infrastructure.database.session import get_db_session
from infrastructure.redis import redis
from infrastructure.services.hook_router import HookRouterService
from infrastructure.services.messenger_link import MessengerLinkService

hooks_router = APIRouter(prefix="/api/v1/hooks", tags=["webhooks"])


async def get_redis_client() -> Redis:
    """Provide Redis client."""
    return redis


async def get_otp_service(
    redis_client: Redis = Depends(get_redis_client),
) -> OTPService:
    """Provide OTPService."""
    return OTPService(redis_client)


async def get_session_service(
    redis_client: Redis = Depends(get_redis_client),
) -> SessionService:
    """Provide SessionService."""
    return SessionService(redis_client)


async def get_messenger_link_service(
    otp_service: OTPService = Depends(get_otp_service),
    session: AsyncSession = Depends(get_db_session),
) -> MessengerLinkService:
    """Provide MessengerLinkService."""
    return MessengerLinkService(otp_service, session)


@hooks_router.post(
    "/{messenger_type}/{bot_uuid}",
    status_code=status.HTTP_200_OK,
    summary="Dynamic webhook handler for messengers",
    response_description="200 OK (always — Telegram requires fast response)",
)
async def handle_webhook(
    messenger_type: str,
    bot_uuid: uuid.UUID,
    payload: dict,
    x_max_bot_api_secret: str | None = Header(None),
    session: AsyncSession = Depends(get_db_session),
    otp_service: OTPService = Depends(get_otp_service),
    session_service: SessionService = Depends(get_session_service),
    messenger_link_service: MessengerLinkService = Depends(get_messenger_link_service),
) -> dict[str, str]:
    """Dynamic webhook handler.

    Processing pipeline:
    1. Lookup BotInstance by bot_uuid
    2. Validate messenger_type matches + status=active
    3. Create adapter for this bot instance (lazy)
    4. Parse payload via adapter → IncomingEnvelope
    5. Inject bot_instance_id into envelope
    6. Resolve user by messenger_user_id
    7. If user not found → OTP-intercept logic
    8. If user found → dispatch to SessionService

    Always returns 200 immediately (Telegram requires response within 60s).
    """
    hook_service = HookRouterService(
        session=session,
        redis=redis,
        otp_service=otp_service,
        session_service=session_service,
        messenger_link_service=messenger_link_service,
    )

    # Verify MAX webhook secret if present
    if messenger_type == "MX" and x_max_bot_api_secret is not None:
        from infrastructure.database.models.bot_instance import BotInstanceTable
        bot = await session.get(BotInstanceTable, bot_uuid)
        if bot is None or bot.secret != x_max_bot_api_secret:
            return {"status": "rejected"}

    status_code, message = await hook_service.process_webhook(
        messenger_type, bot_uuid, payload
    )

    if status_code != 200:
        # Log but still return 200 for Telegram compatibility
        # In production, return proper status for non-Telegram messengers
        pass

    return {"status": "ok"}
