"""Unit tests for BaseHttpAdapter proxy support."""

import pytest
from unittest.mock import patch
from infrastructure.messengers.base import BaseHttpAdapter


class MockAdapter(BaseHttpAdapter):
    """Simple adapter for testing BaseHttpAdapter."""

    pass


@pytest.mark.asyncio
async def test_base_http_adapter_no_proxy():
    """Verify that without a proxy, httpx.AsyncClient is created without proxy arg."""
    with patch("infrastructure.messengers.base.settings") as mock_settings:
        mock_settings.telegram_proxy = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            adapter = MockAdapter()
            await adapter._get_http_client()

            mock_client_cls.assert_called_once()
            kwargs = mock_client_cls.call_args[1]
            assert "proxy" not in kwargs
            assert kwargs["timeout"] == 30.0


@pytest.mark.asyncio
async def test_base_http_adapter_with_proxy():
    """Verify that with a proxy, httpx.AsyncClient is created with proxy arg."""
    proxy_url = "http://proxy.example.com:8080"
    with patch("infrastructure.messengers.base.settings") as mock_settings:
        mock_settings.telegram_proxy = proxy_url

        with patch("httpx.AsyncClient") as mock_client_cls:
            adapter = MockAdapter()
            await adapter._get_http_client()

            mock_client_cls.assert_called_once()
            kwargs = mock_client_cls.call_args[1]
            assert kwargs["proxy"] == proxy_url
            assert kwargs["timeout"] == 30.0
