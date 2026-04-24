"""Unit tests for YandexAdapter."""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient

from infrastructure.messengers.yandex import YandexAdapter


@pytest.fixture
def yandex_adapter():
    return YandexAdapter(bot_token="test_yandex_token")


@pytest.mark.asyncio
async def test_yandex_headers(yandex_adapter):
    """Verify OAuth token is correctly set in headers."""
    headers = yandex_adapter._headers()
    assert headers == {"Authorization": "OAuth test_yandex_token"}


@pytest.mark.asyncio
async def test_yandex_send_text(yandex_adapter):
    """Verify send_text makes correct HTTP request."""
    mock_client = AsyncMock(spec=AsyncClient)

    # Mock the response object
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_client.post.return_value = mock_response
    yandex_adapter._http = mock_client

    await yandex_adapter.send_text(chat_id="123", text="Hello Yandex")

    mock_client.post.assert_awaited_once_with(
        "https://botapi.messenger.yandex.net/bot/v1/messages/sendText/",
        json={"chat_id": "123", "text": "Hello Yandex"},
        headers={"Authorization": "OAuth test_yandex_token"},
    )


@pytest.mark.asyncio
async def test_yandex_send_text_network_error(yandex_adapter):
    """Verify send_text handles httpx.RequestError by raising ValueError."""
    mock_client = AsyncMock(spec=AsyncClient)
    mock_client.post.side_effect = httpx.RequestError("Network failed")
    yandex_adapter._http = mock_client

    with pytest.raises(ValueError, match="Network error sending text message"):
        await yandex_adapter.send_text(chat_id="123", text="Hello Yandex")


@pytest.mark.asyncio
async def test_yandex_unimplemented_methods(yandex_adapter):
    """Verify unimplemented methods raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        await yandex_adapter.parse_webhook({}, "token")

    with pytest.raises(NotImplementedError):
        await yandex_adapter.send_file("123", "path/to/file")

    with pytest.raises(NotImplementedError):
        await yandex_adapter.download_file("file_id", "dest")

    with pytest.raises(NotImplementedError):
        await yandex_adapter.register_webhook("http://webhook.com")
