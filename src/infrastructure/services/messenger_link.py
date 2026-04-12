"""Messenger linking service — links messenger IDs to users after OTP verification.

This service lives in infrastructure because it depends on SQLAlchemy models.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.messenger import MESSENGER_TYPE_TO_FIELD
from core.services.otp import OTPService
from infrastructure.database.models.user import UserTable


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

        Uses reverse OTP lookup to find user_id from code.

        :returns: user_id if successful, None if code is invalid or messenger_type unknown.
        """
        # Find user by OTP code (reverse lookup)
        user_id = await self._otp_service.verify_code_by_value(code)
        if user_id is None:
            return None

        messenger_field = MESSENGER_TYPE_TO_FIELD.get(messenger_type)
        if messenger_field is None:
            return None

        user = await self._session.get(UserTable, user_id)
        if user is None:
            return None

        setattr(user, messenger_field, messenger_id)
        await self._session.flush()
        return user_id
