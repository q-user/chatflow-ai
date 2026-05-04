"""Unit tests for MaxAdapter."""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient

from infrastructure.messengers.max import (
    MaxAdapter,
    _build_inline_keyboard,
)


@pytest.fixture
def max_adapter():
    return MaxAdapter(bot_token="test_max_token")


def _mock_response(status_code=200, json_data=None, content=b""):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status.return_value = None
    if json_data is not None:
        resp.json.return_value = json_data
    resp.content = content
    return resp


# ──────────────────────────────────────────────
# Headers
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_headers(max_adapter):
    """Verify token is set in headers WITHOUT Bearer prefix."""
    headers = max_adapter._headers()
    assert headers == {"Authorization": "test_max_token"}


# ──────────────────────────────────────────────
# parse_webhook
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_webhook_text_message(max_adapter):
    """parse_webhook extracts text message from MAX update."""
    payload = {
        "update_type": "message_created",
        "timestamp": 1702323240,
        "message": {
            "sender": {"user_id": 42, "name": "Ivan", "username": "ivan"},
            "recipient": {"user_id": 99},
            "body": {"mid": "msg-1", "text": "Hello bot"},
            "timestamp": 1702323240,
        },
    }
    envelope = await max_adapter.parse_webhook(payload, "token")
    assert envelope.messenger_type == "MX"
    assert envelope.messenger_user_id == "42"
    assert envelope.chat_id == "42"  # DM → user_id
    assert envelope.text == "Hello bot"
    assert envelope.is_callback is False
    assert envelope.file_id is None


@pytest.mark.asyncio
async def test_parse_webhook_group_chat(max_adapter):
    """parse_webhook uses recipient.chat_id for group chats."""
    payload = {
        "update_type": "message_created",
        "timestamp": 1702323240,
        "message": {
            "sender": {"user_id": 42, "name": "Ivan"},
            "recipient": {"chat_id": 123456789},
            "body": {"mid": "msg-2", "text": "Group message"},
            "timestamp": 1702323240,
        },
    }
    envelope = await max_adapter.parse_webhook(payload, "token")
    assert envelope.chat_id == "123456789"


@pytest.mark.asyncio
async def test_parse_webhook_file_attachment(max_adapter):
    """parse_webhook extracts file URL from attachment."""
    payload = {
        "update_type": "message_created",
        "timestamp": 1702323240,
        "message": {
            "sender": {"user_id": 42, "name": "Ivan"},
            "recipient": {"user_id": 99},
            "body": {
                "mid": "msg-3",
                "text": "Here is the file",
                "attachments": [
                    {
                        "type": "file",
                        "payload": {
                            "url": "https://cdn.max.ru/files/abc123",
                            "filename": "report.pdf",
                            "mime_type": "application/pdf",
                        },
                    }
                ],
            },
            "timestamp": 1702323240,
        },
    }
    envelope = await max_adapter.parse_webhook(payload, "token")
    assert envelope.file_id == "https://cdn.max.ru/files/abc123"
    assert envelope.file_name == "report.pdf"
    assert envelope.file_type == "application/pdf"


@pytest.mark.asyncio
async def test_parse_webhook_image_attachment(max_adapter):
    """parse_webhook extracts image URL from attachment."""
    payload = {
        "update_type": "message_created",
        "timestamp": 1702323240,
        "message": {
            "sender": {"user_id": 42, "name": "Ivan"},
            "recipient": {"user_id": 99},
            "body": {
                "mid": "msg-4",
                "text": None,
                "attachments": [
                    {
                        "type": "image",
                        "payload": {"url": "https://cdn.max.ru/img/xyz"},
                    }
                ],
            },
            "timestamp": 1702323240,
        },
    }
    envelope = await max_adapter.parse_webhook(payload, "token")
    assert envelope.file_id == "https://cdn.max.ru/img/xyz"
    assert envelope.file_type == "image/jpeg"


@pytest.mark.asyncio
async def test_parse_webhook_callback(max_adapter):
    """parse_webhook handles message_callback (button press)."""
    payload = {
        "update_type": "message_callback",
        "timestamp": 1702323240,
        "callback": {
            "callback_id": "cb-123",
            "payload": "action_data",
            "user": {"user_id": 42, "name": "Ivan"},
            "chat": {"chat_id": 123456789},
        },
    }
    envelope = await max_adapter.parse_webhook(payload, "token")
    assert envelope.is_callback is True
    assert envelope.text == "action_data"
    assert envelope.raw_callback_id == "cb-123"
    assert envelope.messenger_user_id == "42"
    assert envelope.chat_id == "123456789"


@pytest.mark.asyncio
async def test_parse_webhook_no_update_type_raises(max_adapter):
    """parse_webhook raises ValueError when no update_type."""
    with pytest.raises(ValueError, match="No update_type"):
        await max_adapter.parse_webhook({}, "token")


@pytest.mark.asyncio
async def test_parse_webhook_unsupported_type_raises(max_adapter):
    """parse_webhook raises ValueError for unsupported update_type."""
    with pytest.raises(ValueError, match="Unsupported MAX update_type"):
        await max_adapter.parse_webhook({"update_type": "bot_started"}, "token")


@pytest.mark.asyncio
async def test_parse_webhook_no_sender_raises(max_adapter):
    """parse_webhook raises ValueError when no sender info."""
    payload = {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": {},
            "recipient": {},
            "body": {"mid": "1", "text": "hi"},
            "timestamp": 1,
        },
    }
    with pytest.raises(ValueError, match="No sender.user_id"):
        await max_adapter.parse_webhook(payload, "token")


# ──────────────────────────────────────────────
# send_text
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_text(max_adapter):
    """Verify send_text posts to /messages."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response()
    max_adapter._http = mock_client

    await max_adapter.send_text(chat_id="42", text="Hello MAX")

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://platform-api.max.ru/messages"
    assert call_args[1]["params"]["user_id"] == "42"
    assert call_args[1]["json"] == {"text": "Hello MAX"}


@pytest.mark.asyncio
async def test_send_text_with_buttons(max_adapter):
    """Verify send_text includes inline_keyboard attachment."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response()
    max_adapter._http = mock_client

    buttons = [[{"text": "Yes", "payload": "yes"}, {"text": "No", "payload": "no"}]]
    await max_adapter.send_text(chat_id="42", text="Choose", buttons=buttons)

    call_kwargs = mock_client.post.call_args[1]
    assert "attachments" in call_kwargs["json"]
    att = call_kwargs["json"]["attachments"][0]
    assert att["type"] == "inline_keyboard"
    assert len(att["payload"]["buttons"]) == 1  # one row
    assert len(att["payload"]["buttons"][0]) == 2  # two buttons
    assert att["payload"]["buttons"][0][0]["type"] == "callback"


@pytest.mark.asyncio
async def test_send_text_network_error(max_adapter):
    """Verify send_text raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("Network failed")
    max_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error sending text message"):
        await max_adapter.send_text(chat_id="42", text="Hello MAX")


# ──────────────────────────────────────────────
# send_file
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_file(tmp_path, max_adapter):
    """Verify send_file performs 2-step upload flow."""
    mock_client = AsyncMock(spec=AsyncClient)

    # Step 1: /uploads returns upload URL
    # Step 2: upload to URL returns token
    # Step 3: /messages sends message with attachment
    uploads_resp = _mock_response(json_data={"url": "https://upload.max.ru/abc"})
    upload_resp = _mock_response(json_data={"token": "file-token-123"})
    send_resp = _mock_response()

    mock_client.post.side_effect = [uploads_resp, upload_resp, send_resp]
    max_adapter._http = mock_client

    test_file = tmp_path / "report.csv"
    test_file.write_text("a,b\n1,2")

    await max_adapter.send_file(chat_id="42", file_path=str(test_file))

    assert mock_client.post.call_count == 3
    # Last call should be /messages with attachment
    last_call = mock_client.post.call_args_list[2]
    assert "attachments" in last_call[1]["json"]
    assert last_call[1]["json"]["attachments"][0]["type"] == "file"


@pytest.mark.asyncio
async def test_send_file_network_error(tmp_path, max_adapter):
    """Verify send_file raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("fail")
    max_adapter._http = mock_client

    test_file = tmp_path / "test.txt"
    test_file.write_text("data")

    with pytest.raises(ValueError, match="Network error"):
        await max_adapter.send_file(chat_id="42", file_path=str(test_file))


# ──────────────────────────────────────────────
# download_file
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_file(tmp_path, max_adapter):
    """Verify download_file saves content from URL."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.get.return_value = _mock_response(content=b"file-bytes")
    max_adapter._http = mock_client

    dest = tmp_path / "downloaded.txt"
    result = await max_adapter.download_file("https://cdn.max.ru/files/abc", str(dest))

    assert result == str(dest)
    assert dest.read_bytes() == b"file-bytes"
    call_args = mock_client.get.call_args
    assert call_args[0][0] == "https://cdn.max.ru/files/abc"


@pytest.mark.asyncio
async def test_download_file_network_error(max_adapter):
    """Verify download_file raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.get.side_effect = httpx.RequestError("fail")
    max_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error downloading file"):
        await max_adapter.download_file("https://cdn.max.ru/files/abc", "/tmp/dest")


# ──────────────────────────────────────────────
# register_webhook
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_webhook_success(max_adapter):
    """Verify register_webhook posts to /subscriptions."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response(json_data={"success": True})
    max_adapter._http = mock_client

    await max_adapter.register_webhook("https://example.com/hook")

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://platform-api.max.ru/subscriptions"
    body = call_args[1]["json"]
    assert body["url"] == "https://example.com/hook"
    assert "message_created" in body["update_types"]
    assert "message_callback" in body["update_types"]


@pytest.mark.asyncio
async def test_register_webhook_with_secret(max_adapter):
    """Verify register_webhook includes secret in body when provided."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response(json_data={"success": True})
    max_adapter._http = mock_client

    await max_adapter.register_webhook("https://example.com/hook", secret="my-secret")

    call_args = mock_client.post.call_args
    body = call_args[1]["json"]
    assert body["secret"] == "my-secret"


@pytest.mark.asyncio
async def test_register_webhook_without_secret(max_adapter):
    """Verify register_webhook omits secret when not provided."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response(json_data={"success": True})
    max_adapter._http = mock_client

    await max_adapter.register_webhook("https://example.com/hook")

    body = mock_client.post.call_args[1]["json"]
    assert "secret" not in body


@pytest.mark.asyncio
async def test_register_webhook_rejected(max_adapter):
    """Verify register_webhook raises ValueError when API rejects."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response(
        json_data={"success": False, "message": "Invalid URL"}
    )
    max_adapter._http = mock_client

    with pytest.raises(ValueError, match="MAX webhook registration failed"):
        await max_adapter.register_webhook("bad-url")


@pytest.mark.asyncio
async def test_register_webhook_network_error(max_adapter):
    """Verify register_webhook raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("timeout")
    max_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error registering webhook"):
        await max_adapter.register_webhook("https://example.com/hook")


# ──────────────────────────────────────────────
# answer_callback
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_answer_callback(max_adapter):
    """Verify answer_callback posts to /answers."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response()
    max_adapter._http = mock_client

    await max_adapter.answer_callback("cb-123")

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://platform-api.max.ru/answers"
    assert call_args[1]["params"]["callback_id"] == "cb-123"
    assert call_args[1]["json"] == {"notification": "OK"}


@pytest.mark.asyncio
async def test_answer_callback_network_error(max_adapter):
    """Verify answer_callback raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("fail")
    max_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error answering callback"):
        await max_adapter.answer_callback("cb-123")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def test_build_inline_keyboard():
    """Verify button format conversion."""
    buttons = [[{"text": "Yes", "payload": "yes"}]]
    result = _build_inline_keyboard(buttons)
    assert result["type"] == "inline_keyboard"
    btn = result["payload"]["buttons"][0][0]
    assert btn["type"] == "callback"
    assert btn["text"] == "Yes"
    assert btn["payload"] == "yes"
