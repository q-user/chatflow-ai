"""Unit tests for Telegram adapter."""

import uuid
from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def callback_query_payload() -> dict:
    """Telegram webhook payload for a callback_query (button press)."""
    return {
        "update_id": 12348,
        "callback_query": {
            "id": "callback_query_id_123",
            "from": {"id": 999888777, "is_bot": False, "first_name": "Test"},
            "message": {
                "message_id": 10,
                "chat": {"id": 123456789, "type": "private"},
                "date": 1234567890,
                "text": "Original message",
            },
            "data": "/compile",
        },
    }


@pytest.mark.asyncio
async def test_parse_webhook_callback_query(
    adapter: TelegramAdapter, callback_query_payload: dict
):
    """callback_query → IncomingEnvelope with is_callback=True and raw_callback_id."""
    envelope = await adapter.parse_webhook(callback_query_payload, "test_bot_token_123")

    assert envelope.messenger_user_id == "999888777"
    assert envelope.chat_id == "123456789"
    assert envelope.text == "/compile"  # button payload → text
    assert envelope.is_callback is True
    assert envelope.raw_callback_id == "callback_query_id_123"
    assert envelope.messenger_type == "TG"


@pytest.mark.asyncio
async def test_parse_webhook_callback_query_priority_over_message(
    adapter: TelegramAdapter, callback_query_payload: dict
):
    """callback_query takes priority over message if both present."""
    # Add a message to payload — callback_query should still win
    callback_query_payload["message"] = {
        "message_id": 99,
        "from": {"id": 111},
        "chat": {"id": 222},
        "date": 1234567890,
        "text": "Ignored message",
    }
    envelope = await adapter.parse_webhook(callback_query_payload, "token")
    assert envelope.is_callback is True
    assert envelope.text == "/compile"


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


# ──────────────────────────────────────────────
# register_webhook tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_webhook_success():
    """Valid token + 200 ok=true → no exception."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": True}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    adapter = TelegramAdapter(bot_token="test_token", http_client=mock_client)
    await adapter.register_webhook("https://example.com/webhook")

    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["data"]["url"] == "https://example.com/webhook"


@pytest.mark.asyncio
async def test_register_webhook_non_200_status():
    """Non-200 response → ValueError with status code."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    adapter = TelegramAdapter(bot_token="bad_token", http_client=mock_client)

    with pytest.raises(ValueError, match="Telegram API rejected webhook.*401"):
        await adapter.register_webhook("https://example.com/webhook")


@pytest.mark.asyncio
async def test_register_webhook_ok_false():
    """ok=false in response → ValueError with description."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": False,
        "description": "Wrong response from the webhook",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    adapter = TelegramAdapter(bot_token="test_token", http_client=mock_client)

    with pytest.raises(ValueError, match="ok=false.*Wrong response"):
        await adapter.register_webhook("https://example.com/webhook")
