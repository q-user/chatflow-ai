"""Unified incoming message schema for all messengers."""

from uuid import UUID

from pydantic import BaseModel
from core.domain.messenger import MessengerType


class IncomingEnvelope(BaseModel):
    """Unified incoming message from any messenger.

    This is the contract between messenger adapters and the application core.
    """

    messenger_user_id: str  # telegram_id / yandex_id / max_id
    chat_id: str  # chat/group ID for replies
    text: str | None = None  # message text (or command / callback_data)
    file_id: str | None = None  # file ID in the messenger
    file_type: str | None = None  # MIME: "application/pdf", "image/png", etc.
    file_name: str | None = None  # original file name
    bot_instance_id: UUID | None = None  # set by router after parse
    messenger_type: MessengerType  # validated against allowed values
    is_callback: bool = False  # True if from button press (callback_query)
    raw_callback_id: str | None = (
        None  # Telegram callback_query_id, None for non-callback
    )

    @property
    def is_otp_pattern(self) -> bool:
        """True if text is a 6-digit code (OTP verification pattern)."""
        return bool(self.text and self.text.isdigit() and len(self.text) == 6)

    @property
    def is_command(self) -> bool:
        """True if text starts with /."""
        return bool(self.text and self.text.startswith("/"))


class OutgoingMessage(BaseModel):
    """Unified outgoing message to any messenger."""

    chat_id: str
    text: str | None = None
    file_path: str | None = None  # local path to file for sending
    caption: str | None = None  # caption for file
