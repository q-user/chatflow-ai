"""Unit tests for YandexAdapter."""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient

from infrastructure.messengers.yandex import (
    YandexAdapter,
    _build_suggest_buttons,
    _guess_mime_from_name,
)


@pytest.fixture
def yandex_adapter():
    return YandexAdapter(bot_token="test_yandex_token")


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
async def test_yandex_headers(yandex_adapter):
    """Verify OAuth token is correctly set in headers."""
    headers = yandex_adapter._headers()
    assert headers == {"Authorization": "OAuth test_yandex_token"}


# ──────────────────────────────────────────────
# parse_webhook
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_webhook_text_message(yandex_adapter):
    """parse_webhook extracts text message from Yandex update."""
    payload = {
        "updates": [{
            "from": {"id": "guid-1", "login": "user@yandex.ru"},
            "chat": {"type": "private"},
            "text": "Hello bot",
            "message_id": 100,
            "update_id": 1,
            "timestamp": 1702323240,
        }],
        "ok": True,
    }
    envelope = await yandex_adapter.parse_webhook(payload, "token")
    assert envelope.messenger_type == "YM"
    assert envelope.messenger_user_id == "user@yandex.ru"
    assert envelope.chat_id == "user@yandex.ru"  # private chat → login
    assert envelope.text == "Hello bot"
    assert envelope.is_callback is False
    assert envelope.file_id is None


@pytest.mark.asyncio
async def test_parse_webhook_group_chat(yandex_adapter):
    """parse_webhook uses chat.id for group chats."""
    payload = {
        "updates": [{
            "from": {"id": "guid-1", "login": "user@yandex.ru"},
            "chat": {"type": "group", "id": "0/0/chat-guid"},
            "text": "Group message",
            "message_id": 101,
            "update_id": 2,
            "timestamp": 1702323240,
        }],
        "ok": True,
    }
    envelope = await yandex_adapter.parse_webhook(payload, "token")
    assert envelope.chat_id == "0/0/chat-guid"


@pytest.mark.asyncio
async def test_parse_webhook_file_attachment(yandex_adapter):
    """parse_webhook extracts file attachment."""
    payload = {
        "updates": [{
            "from": {"id": "guid-1", "login": "user@yandex.ru"},
            "chat": {"type": "private"},
            "file": {"id": "disk/file-guid", "name": "report.pdf", "size": 1024},
            "message_id": 102,
            "update_id": 3,
            "timestamp": 1702323240,
        }],
        "ok": True,
    }
    envelope = await yandex_adapter.parse_webhook(payload, "token")
    assert envelope.file_id == "disk/file-guid"
    assert envelope.file_name == "report.pdf"
    assert envelope.file_type == "application/pdf"


@pytest.mark.asyncio
async def test_parse_webhook_image(yandex_adapter):
    """parse_webhook extracts largest image variant."""
    payload = {
        "updates": [{
            "from": {"id": "guid-1", "login": "user@yandex.ru"},
            "chat": {"type": "private"},
            "images": [[
                {"file_id": "disk/img?size=small", "width": 150, "height": 10},
                {"file_id": "disk/img?size=middle", "width": 250, "height": 18},
                {"file_id": "disk/img", "width": 1048, "height": 78,
                 "size": 20362, "name": "photo.jpeg"},
            ]],
            "message_id": 103,
            "update_id": 4,
            "timestamp": 1702323240,
        }],
        "ok": True,
    }
    envelope = await yandex_adapter.parse_webhook(payload, "token")
    assert envelope.file_id == "disk/img"
    assert envelope.file_type == "image/jpeg"


@pytest.mark.asyncio
async def test_parse_webhook_bot_request_callback(yandex_adapter):
    """parse_webhook handles bot_request (button press) as callback."""
    payload = {
        "updates": [{
            "from": {"id": "guid-1", "login": "user@yandex.ru"},
            "chat": {"type": "private"},
            "bot_request": {
                "server_action": {"name": "action_name", "payload": "action_data"},
                "element_id": "btn-1",
            },
            "message_id": 104,
            "update_id": 5,
            "timestamp": 1702323240,
        }],
        "ok": True,
    }
    envelope = await yandex_adapter.parse_webhook(payload, "token")
    assert envelope.is_callback is True
    assert envelope.text == "action_data"
    assert envelope.raw_callback_id == "btn-1"


@pytest.mark.asyncio
async def test_parse_webhook_no_updates_raises(yandex_adapter):
    """parse_webhook raises ValueError when no updates."""
    with pytest.raises(ValueError, match="No updates"):
        await yandex_adapter.parse_webhook({"ok": True}, "token")


@pytest.mark.asyncio
async def test_parse_webhook_no_sender_raises(yandex_adapter):
    """parse_webhook raises ValueError when no sender info."""
    payload = {
        "updates": [{
            "chat": {"type": "private"},
            "text": "hi",
            "message_id": 1,
            "update_id": 1,
            "timestamp": 1,
        }],
        "ok": True,
    }
    with pytest.raises(ValueError, match="No sender"):
        await yandex_adapter.parse_webhook(payload, "token")


# ──────────────────────────────────────────────
# send_text
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_yandex_send_text(yandex_adapter):
    """Verify send_text makes correct HTTP request."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response()
    yandex_adapter._http = mock_client

    await yandex_adapter.send_text(chat_id="123", text="Hello Yandex")

    mock_client.post.assert_awaited_once_with(
        "https://botapi.messenger.yandex.net/bot/v1/messages/sendText/",
        json={"chat_id": "123", "text": "Hello Yandex"},
        headers={"Authorization": "OAuth test_yandex_token"},
    )


@pytest.mark.asyncio
async def test_yandex_send_text_with_buttons(yandex_adapter):
    """Verify send_text includes suggest_buttons when buttons provided."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response()
    yandex_adapter._http = mock_client

    buttons = [[{"text": "Yes", "payload": "yes"}, {"text": "No", "payload": "no"}]]
    await yandex_adapter.send_text(chat_id="123", text="Choose", buttons=buttons)

    call_kwargs = mock_client.post.call_args[1]
    assert "suggest_buttons" in call_kwargs["json"]
    sb = call_kwargs["json"]["suggest_buttons"]
    assert sb["layout"] == "true"
    assert len(sb["buttons"]) == 1  # one row
    assert len(sb["buttons"][0]) == 2  # two buttons


@pytest.mark.asyncio
async def test_yandex_send_text_network_error(yandex_adapter):
    """Verify send_text handles httpx.RequestError by raising ValueError."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("Network failed")
    yandex_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error sending text message"):
        await yandex_adapter.send_text(chat_id="123", text="Hello Yandex")


# ──────────────────────────────────────────────
# send_file
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_file(tmp_path, yandex_adapter):
    """Verify send_file posts multipart/form-data."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response()
    yandex_adapter._http = mock_client

    test_file = tmp_path / "report.csv"
    test_file.write_text("a,b\n1,2")

    await yandex_adapter.send_file(chat_id="123", file_path=str(test_file))

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://botapi.messenger.yandex.net/bot/v1/messages/sendFile/"
    assert "files" in call_args[1]
    assert "data" in call_args[1]
    assert call_args[1]["data"]["chat_id"] == "123"


@pytest.mark.asyncio
async def test_send_file_network_error(tmp_path, yandex_adapter):
    """Verify send_file raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("fail")
    yandex_adapter._http = mock_client

    test_file = tmp_path / "test.txt"
    test_file.write_text("data")

    with pytest.raises(ValueError, match="Network error sending file"):
        await yandex_adapter.send_file(chat_id="123", file_path=str(test_file))


# ──────────────────────────────────────────────
# download_file
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_file(tmp_path, yandex_adapter):
    """Verify download_file saves binary content from getFile."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response(content=b"file-content-bytes")
    yandex_adapter._http = mock_client

    dest = tmp_path / "downloaded.txt"
    result = await yandex_adapter.download_file("disk/file-guid", str(dest))

    assert result == str(dest)
    assert dest.read_bytes() == b"file-content-bytes"
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://botapi.messenger.yandex.net/bot/v1/messages/getFile/"
    assert call_args[1]["data"]["file_id"] == "disk/file-guid"


@pytest.mark.asyncio
async def test_download_file_network_error(yandex_adapter):
    """Verify download_file raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("fail")
    yandex_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error downloading file"):
        await yandex_adapter.download_file("disk/guid", "/tmp/dest")


# ──────────────────────────────────────────────
# register_webhook
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_webhook_success(yandex_adapter):
    """Verify register_webhook posts to /self/update/."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response(
        json_data={"ok": True, "webhook_url": "https://example.com/hook"}
    )
    yandex_adapter._http = mock_client

    await yandex_adapter.register_webhook("https://example.com/hook")

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "https://botapi.messenger.yandex.net/bot/v1/self/update/"
    assert call_args[1]["json"] == {"webhook_url": "https://example.com/hook"}


@pytest.mark.asyncio
async def test_register_webhook_rejected(yandex_adapter):
    """Verify register_webhook raises ValueError when API rejects."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.return_value = _mock_response(
        json_data={"ok": False, "description": "Invalid URL"}
    )
    yandex_adapter._http = mock_client

    with pytest.raises(ValueError, match="Yandex webhook registration failed"):
        await yandex_adapter.register_webhook("bad-url")


@pytest.mark.asyncio
async def test_register_webhook_network_error(yandex_adapter):
    """Verify register_webhook raises ValueError on network error."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("timeout")
    yandex_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error registering webhook"):
        await yandex_adapter.register_webhook("https://example.com/hook")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def test_build_suggest_buttons():
    """Verify button format conversion."""
    buttons = [[{"text": "Yes", "payload": "yes"}]]
    result = _build_suggest_buttons(buttons)
    assert result["layout"] == "true"
    assert len(result["buttons"]) == 1
    btn = result["buttons"][0][0]
    assert btn["title"] == "Yes"
    assert btn["directives"][0]["type"] == "server_action"
    assert btn["directives"][0]["payload"] == "yes"


def test_guess_mime_from_name():
    """Verify MIME type guessing from filename."""
    assert _guess_mime_from_name("report.pdf") == "application/pdf"
    assert _guess_mime_from_name("photo.jpg") == "image/jpeg"
    assert _guess_mime_from_name("audio.ogg") == "audio/ogg"
    assert _guess_mime_from_name("unknown.xyz") == "application/octet-stream"
