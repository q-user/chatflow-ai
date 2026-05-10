"""Messenger linking service — links messenger IDs to users after OTP verification.

This service lives in infrastructure because it depends on SQLAlchemy models.
"""

import uuid

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.messenger import MESSENGER_TYPE_TO_FIELD
from core.services.otp import OTPService
from infrastructure.database.models.user import UserTable

# Pre-computed bcrypt hash of an impossible password for shadow users.
# Structurally valid so fastapi-users doesn't crash on password checks,
# but will never verify successfully.
_SHADOW_PASSWORD_HASH = bcrypt.hashpw(
    b"__shadow_user__", bcrypt.gensalt()
).decode()


class MessengerLinkService:
    """Links messenger IDs (telegram_id, yandex_id) to users after OTP verification."""

    def __init__(self, otp_service: OTPService, session: AsyncSession) -> None:
        self._otp_service = otp_service
        self._session = session

    async def link_by_otp(
        self,
        code: str,
        messenger_type: str,
        messenger_id: str,
    ) -> uuid.UUID | None:
        """Verify OTP code and link messenger to the identified user.

        Uses reverse OTP lookup first, then falls back to invite code
        (lazy Shadow User creation).

        :returns: user_id if successful, None if code is invalid or messenger_type unknown.
        """
        # 1. Standard OTP reverse lookup
        user_id = await self._otp_service.verify_code_by_value(code)
        if user_id is not None:
            messenger_field = MESSENGER_TYPE_TO_FIELD.get(messenger_type)
            if messenger_field is None:
                return None
            user = await self._session.get(UserTable, user_id)
            if user is None:
                return None
            setattr(user, messenger_field, messenger_id)
            await self._session.flush()
            return user_id

        # 2. Invite code fallback → lazy Shadow User creation
        company_id = await self._otp_service.verify_invite_code(code)
        if company_id is None:
            return None

        messenger_field = MESSENGER_TYPE_TO_FIELD.get(messenger_type)
        if messenger_field is None:
            return None

        new_user = UserTable(
            email=f"invite_{uuid.uuid4().hex[:8]}@chatflow.local",
            hashed_password=_SHADOW_PASSWORD_HASH,
            company_id=company_id,
            is_active=True,
            is_verified=False,
            is_superuser=False,
        )
        self._session.add(new_user)
        await self._session.flush()
        setattr(new_user, messenger_field, messenger_id)
        await self._session.flush()
        return new_user.id
