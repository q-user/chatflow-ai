"""Unit tests for delivery service async wrappers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from infrastructure.services.delivery import _send_text_message, _deliver_artifact


class TestDeliveryAsyncWrapper:
    """CRITICAL #2: _send_text_message must not crash when called from running loop."""

    def test_send_text_from_sync_context(self):
        """Works from sync context (Celery) — no running loop."""
        adapter = AsyncMock()
        factory = MagicMock(return_value=adapter)

        _send_text_message("token", "TG", "chat_123", "hello", adapter_factory=factory)

        adapter.send_text.assert_awaited_once_with(chat_id="chat_123", text="hello")
        adapter.aclose.assert_awaited_once()

    def test_deliver_artifact_from_sync_context(self, tmp_path):
        """Works from sync context — no running loop."""
        adapter = AsyncMock()
        factory = MagicMock(return_value=adapter)
        artifact = tmp_path / "test.csv"
        artifact.write_text("data")

        snapshot = {
            "bot_token": "token",
            "messenger_type": "TG",
            "chat_id": "chat_123",
        }
        _deliver_artifact(snapshot, str(artifact), adapter_factory=factory)

        adapter.send_file.assert_awaited_once()
        adapter.aclose.assert_awaited_once()

    def test_send_text_from_running_loop(self):
        """Must not raise RuntimeError when called from running event loop."""
        adapter = AsyncMock()
        factory = MagicMock(return_value=adapter)

        async def caller():
            _send_text_message(
                "token", "TG", "chat_123", "hello", adapter_factory=factory
            )

        # Should not raise RuntimeError("asyncio.run() cannot be called...")
        asyncio.run(caller())
        adapter.send_text.assert_awaited_once()
        adapter.aclose.assert_awaited_once()

    def test_deliver_artifact_from_running_loop(self, tmp_path):
        """Must not raise RuntimeError when called from running event loop."""
        adapter = AsyncMock()
        factory = MagicMock(return_value=adapter)
        artifact = tmp_path / "test.csv"
        artifact.write_text("data")

        snapshot = {
            "bot_token": "token",
            "messenger_type": "TG",
            "chat_id": "chat_123",
        }

        async def caller():
            _deliver_artifact(snapshot, str(artifact), adapter_factory=factory)

        asyncio.run(caller())
        adapter.send_file.assert_awaited_once()
        adapter.aclose.assert_awaited_once()
