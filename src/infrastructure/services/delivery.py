"""Messenger delivery service for artifacts and text messages.

Extracted from Celery tasks to decouple delivery logic from task orchestration.
"""

import asyncio
import logging
import os

from infrastructure.messengers import create_adapter as _default_create_adapter

logger = logging.getLogger(__name__)

_adapter_factory = _default_create_adapter


def set_adapter_factory(factory) -> None:
    """Override the adapter factory for testing or custom wiring."""
    global _adapter_factory
    _adapter_factory = factory


def reset_adapter_factory() -> None:
    """Reset the adapter factory to the default create_adapter."""
    global _adapter_factory
    _adapter_factory = _default_create_adapter


def _send_text_message(
    bot_token: str,
    messenger_type: str,
    chat_id: str,
    text: str,
    *,
    adapter_factory=None,
) -> None:
    """Send a plain text message via messenger adapter (sync wrapper)."""
    factory = adapter_factory or _adapter_factory
    adapter = factory(messenger_type, bot_token)

    async def _send() -> None:
        try:
            await adapter.send_text(chat_id=chat_id, text=text)
        finally:
            await adapter.aclose()

    asyncio.run(_send())


def _deliver_artifact(
    snapshot: dict, artifact_path: str, *, adapter_factory=None
) -> None:
    """Send generated artifact back to user via messenger.

    :param snapshot: Session snapshot dict with chat_id, messenger_type, bot_token.
    :param artifact_path: Local path to the file to send.
    """
    bot_token = snapshot.get("bot_token")
    messenger_type = snapshot.get("messenger_type")
    chat_id = snapshot.get("chat_id")
    if not all([bot_token, messenger_type, chat_id]):
        logger.warning("Cannot deliver artifact: missing delivery fields in snapshot")
        return

    factory = adapter_factory or _adapter_factory
    adapter = factory(str(messenger_type), str(bot_token))

    async def _send() -> None:
        try:
            await adapter.send_file(
                chat_id=str(chat_id),
                file_path=artifact_path,
                caption="Результат обработки готов ✅",
            )
        finally:
            await adapter.aclose()
            try:
                os.unlink(artifact_path)
            except OSError:
                logger.warning("Failed to cleanup artifact: %s", artifact_path)

    asyncio.run(_send())
