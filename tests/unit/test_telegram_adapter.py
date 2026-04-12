"""Unit tests for Telegram adapter."""

import uuid

import pytest

from core.domain.incoming import IncomingEnvelope
from infrastructure.messengers.telegram import TelegramAdapter


@pytest.fixture
def adapter() -> TelegramAdapter:
    """Create TelegramAdapter with mock HTTP client."""
    return TelegramAdapter(bot_token="test_bot_token_123")


@pytest.fixture
def text_message_payload() -> dict:
    """Telegram webhook payload for a text message."""
    return {
        "update_id": 12345,
        "message": {
            "message_id": 1,
            "from": {"id": 999888777, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 123456789, "type": "private"},
            "date": 1234567890,
            "text": "Hello, bot!",
        },
    }


@pytest.fixture
def document_message_payload() -> dict:
    """Telegram webhook payload for a document message."""
    return {
        "update_id": 12346,
        "message": {
            "message_id": 2,
            "from": {"id": 999888777, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 123456789, "type": "private"},
            "date": 1234567890,
            "document": {
                "file_id": "BQACAgIAAxkBAAIB",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
            },
            "caption": "Here is the report",
        },
    }


@pytest.fixture
def photo_message_payload() -> dict:
    """Telegram webhook payload for a photo message."""
    return {
        "update_id": 12347,
        "message": {
            "message_id": 3,
            "from": {"id": 999888777, "is_bot": False, "first_name": "Test"},
            "chat": {"id": 123456789, "type": "private"},
            "date": 1234567890,
            "photo": [
                {"file_id": "small_id", "file_size": 100, "width": 100, "height": 100},
                {
                    "file_id": "large_id",
                    "file_size": 5000,
                    "width": 1280,
                    "height": 720,
                },
            ],
        },
    }


# ──────────────────────────────────────────────
# parse_webhook tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_webhook_text_message(
    adapter: TelegramAdapter, text_message_payload: dict
):
    """Text message → IncomingEnvelope with text."""
    envelope = await adapter.parse_webhook(text_message_payload, "test_bot_token_123")

    assert envelope.messenger_user_id == "999888777"
    assert envelope.chat_id == "123456789"
    assert envelope.text == "Hello, bot!"
    assert envelope.file_id is None
    assert envelope.messenger_type == "TG"


@pytest.mark.asyncio
async def test_parse_webhook_document_message(
    adapter: TelegramAdapter, document_message_payload: dict
):
    """Document with caption → IncomingEnvelope with file_id and text from caption."""
    envelope = await adapter.parse_webhook(
        document_message_payload, "test_bot_token_123"
    )

    assert envelope.file_id == "BQACAgIAAxkBAAIB"
    assert envelope.file_type == "application/pdf"
    assert envelope.file_name == "report.pdf"
    assert envelope.text == "Here is the report"  # caption → text


@pytest.mark.asyncio
async def test_parse_webhook_photo_message(
    adapter: TelegramAdapter, photo_message_payload: dict
):
    """Photo → IncomingEnvelope with largest photo file_id."""
    envelope = await adapter.parse_webhook(photo_message_payload, "test_bot_token_123")

    assert envelope.file_id == "large_id"  # Last = largest
    assert envelope.file_type == "image/jpeg"
    assert envelope.text is None


@pytest.mark.asyncio
async def test_parse_webhook_no_message(adapter: TelegramAdapter):
    """Payload without message → ValueError."""
    with pytest.raises(ValueError, match="No message"):
        await adapter.parse_webhook({"update_id": 1}, "token")


@pytest.mark.asyncio
async def test_parse_webhook_sets_placeholder_bot_instance_id(
    adapter: TelegramAdapter, text_message_payload: dict
):
    """bot_instance_id is set to placeholder — router injects real value."""
    envelope = await adapter.parse_webhook(text_message_payload, "test_bot_token_123")
    assert envelope.bot_instance_id is not None  # placeholder UUID
    assert isinstance(envelope.bot_instance_id, uuid.UUID)


@pytest.mark.asyncio
async def test_parse_webhook_edited_message(
    adapter: TelegramAdapter, text_message_payload: dict
):
    """Edited message is handled the same way as regular message."""
    text_message_payload["edited_message"] = text_message_payload.pop("message")
    envelope = await adapter.parse_webhook(text_message_payload, "token")
    assert envelope.text == "Hello, bot!"


# ──────────────────────────────────────────────
# IncomingEnvelope property tests
# ──────────────────────────────────────────────


def test_is_otp_pattern_true():
    """6-digit text → is_otp_pattern = True."""
    env = IncomingEnvelope(
        messenger_user_id="123",
        chat_id="456",
        text="123456",
        bot_instance_id=uuid.uuid4(),
        messenger_type="TG",
    )
    assert env.is_otp_pattern is True


def test_is_otp_pattern_false():
    """Non-6-digit text → is_otp_pattern = False."""
    env = IncomingEnvelope(
        messenger_user_id="123",
        chat_id="456",
        text="/start",
        bot_instance_id=uuid.uuid4(),
        messenger_type="TG",
    )
    assert env.is_otp_pattern is False


def test_is_command_true():
    """Text starting with / → is_command = True."""
    env = IncomingEnvelope(
        messenger_user_id="123",
        chat_id="456",
        text="/start",
        bot_instance_id=uuid.uuid4(),
        messenger_type="TG",
    )
    assert env.is_command is True


def test_is_command_false():
    """Text not starting with / → is_command = False."""
    env = IncomingEnvelope(
        messenger_user_id="123",
        chat_id="456",
        text="Hello",
        bot_instance_id=uuid.uuid4(),
        messenger_type="TG",
    )
    assert env.is_command is False
