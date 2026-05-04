"""Yandex Messenger Bot API adapter via httpx.

API docs: https://yandex.ru/dev/messenger/doc/ru/
Auth: OAuth {bot_token} header

Webhook payload structure (Update):
  {
    "updates": [{
      "from": {"id": "<guid>", "login": "user@yandex.ru"},
      "chat": {"type": "private"|"group"|"channel", "id": "0/0/<guid>"},
      "text": "...",
      "file": {"id": "disk/<guid>", "name": "...", "size": N},
      "images": [[{"file_id": "disk/<guid>", "width": W, "height": H, ...}]],
      "bot_request": {"server_action": {"name": "...", "payload": ...}},
      "message_id": N, "update_id": N, "timestamp": N
    }],
    "ok": true
  }

Key differences from Telegram:
  - Webhook wraps updates in {"updates": [...]} envelope
  - Private chats have no chat.id — use sender login instead
  - Images come as nested arrays (gallery): images[[{size_variants}]]
  - Files downloaded via /messages/getFile/ (returns binary stream)
  - Buttons use SuggestButtons (inline_keyboard is deprecated)
  - Callbacks come as bot_request.server_action (not callback_query)
"""

import logging
import uuid
from pathlib import Path
from typing import Any

import httpx

from core.domain.incoming import IncomingEnvelope
from core.interfaces.messenger import IMessengerAdapter
from infrastructure.messengers.base import BaseHttpAdapter

logger = logging.getLogger(__name__)


class YandexAdapter(BaseHttpAdapter, IMessengerAdapter):
    """Yandex Messenger Bot API adapter.

    API docs: https://botapi.messenger.yandex.net/bot/v1/
    Auth: OAuth {bot_token} header
    """

    BASE_URL = "https://botapi.messenger.yandex.net/bot/v1"

    def __init__(self, bot_token: str, http_client: httpx.AsyncClient | None = None):
        super().__init__(http_client)
        self._bot_token = bot_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"OAuth {self._bot_token}"}

    # ──────────────────────────────────────────────
    # IMessengerAdapter implementation
    # ──────────────────────────────────────────────

    async def parse_webhook(self, payload: dict, bot_token: str) -> IncomingEnvelope:
        """Parse Yandex Update object → IncomingEnvelope.

        Yandex sends {"updates": [{...}], "ok": true}.
        We process the FIRST update only (one webhook per message).

        Handles:
        - bot_request (button press via server_action)
        - text messages
        - file attachments (file / images)

        :param payload: Raw Yandex webhook payload.
        :param bot_token: Bot OAuth token (unused, kept for interface compat).
        :returns: Parsed IncomingEnvelope.
        :raises ValueError: If payload structure is invalid.
        """
        updates = payload.get("updates", [])
        if not updates:
            raise ValueError("No updates in Yandex webhook payload")

        update = updates[0]

        # 1. Extract sender
        sender = update.get("from", {})
        messenger_user_id = sender.get("login") or sender.get("id", "")
        if not messenger_user_id:
            raise ValueError("No sender id/login in Yandex update")

        # 2. Extract chat_id
        chat = update.get("chat", {})
        chat_id = chat.get("id", "")
        # Private chats have no chat.id — use login for 1:1 routing
        if not chat_id and chat.get("type") == "private":
            chat_id = messenger_user_id

        # 3. Check bot_request (button callback) FIRST
        bot_request = update.get("bot_request")
        if bot_request:
            action = bot_request.get("server_action", {})
            callback_text = action.get("payload") or action.get("name", "")
            element_id = bot_request.get("element_id")
            return IncomingEnvelope(
                messenger_user_id=str(messenger_user_id),
                chat_id=str(chat_id),
                text=str(callback_text),
                bot_instance_id=uuid.uuid4(),  # placeholder — set by router
                messenger_type="YM",
                is_callback=True,
                raw_callback_id=str(element_id) if element_id else None,
            )

        # 4. Extract text
        text = update.get("text")

        # 5. Extract file info
        file_id: str | None = None
        file_type: str | None = None
        file_name: str | None = None

        # Single file attachment
        file_obj = update.get("file")
        if file_obj:
            file_id = file_obj.get("id")
            file_name = file_obj.get("name")
            # Guess MIME from extension
            if file_name:
                file_type = _guess_mime_from_name(file_name)

        # Images — take the last (largest) variant of the first image
        images = update.get("images")
        if images and not file_id:
            if images[0]:
                # images is [[{variant1}, {variant2}, ...], ...]
                # Last variant in each sub-array is the original/full-size
                original = images[0][-1] if len(images[0]) > 1 else images[0][0]
                file_id = original.get("file_id")
                file_name = original.get("name")
                file_type = "image/jpeg"  # Yandex images default to JPEG

        return IncomingEnvelope(
            messenger_user_id=str(messenger_user_id),
            chat_id=str(chat_id),
            text=text,
            file_id=file_id,
            file_type=file_type,
            file_name=file_name,
            bot_instance_id=uuid.uuid4(),  # placeholder — set by router
            messenger_type="YM",
        )

    async def send_text(
        self,
        chat_id: str,
        text: str,
        buttons: list[list[dict]] | None = None,
    ) -> None:
        """Send a text message via /messages/sendText/.

        :param chat_id: Target chat ID (or login for private chats).
        :param text: Message text.
        :param buttons: Optional inline keyboard rows.
            Each row is a list of button dicts:
            {"text": "Label", "payload": "action_name"}
            Converted to Yandex SuggestButtons format.
        :raises ValueError: If network error occurs.
        :raises httpx.HTTPStatusError: If API returns an error.
        """
        http = await self._get_http_client()
        url = f"{self.BASE_URL}/messages/sendText/"

        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}

        if buttons:
            payload["suggest_buttons"] = _build_suggest_buttons(buttons)

        try:
            resp = await http.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
        except httpx.RequestError as e:
            raise ValueError(f"Network error sending text message: {e}") from e

    async def send_file(
        self, chat_id: str, file_path: str, caption: str | None = None
    ) -> None:
        """Send a file via /messages/sendFile/.

        :param chat_id: Target chat ID.
        :param file_path: Local path to the file.
        :param caption: Optional caption (Yandex doesn't support caption
            on files — logged as warning if provided).
        :raises ValueError: If network error occurs.
        :raises httpx.HTTPStatusError: If API returns an error.
        """
        if caption:
            logger.warning("Yandex send_file does not support caption — ignored")

        http = await self._get_http_client()
        url = f"{self.BASE_URL}/messages/sendFile/"

        try:
            with open(file_path, "rb") as f:
                files = {"document": (Path(file_path).name, f)}
                data = {"chat_id": chat_id}
                resp = await http.post(
                    url, data=data, files=files, headers=self._headers()
                )
            resp.raise_for_status()
        except httpx.RequestError as e:
            raise ValueError(f"Network error sending file: {e}") from e

    async def download_file(self, file_id: str, dest_path: str) -> str:
        """Download a file via /messages/getFile/.

        Yandex returns the file as a binary stream (not JSON with URL).

        :param file_id: Yandex file ID (e.g. "disk/<guid>").
        :param dest_path: Local destination path.
        :returns: Path to the saved file.
        :raises ValueError: If network error occurs or file_id is invalid.
        """
        http = await self._get_http_client()
        url = f"{self.BASE_URL}/messages/getFile/"

        try:
            resp = await http.post(
                url,
                data={"file_id": file_id},
                headers=self._headers(),
            )
            resp.raise_for_status()

            # Yandex returns binary stream directly
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return str(dest)
        except httpx.RequestError as e:
            raise ValueError(f"Network error downloading file: {e}") from e

    async def register_webhook(
        self, webhook_url: str, secret: str | None = None
    ) -> None:
        """Register a webhook URL via /self/update/.

        :param webhook_url: Full public URL for the webhook endpoint.
        :param secret: Unused for Yandex (kept for interface compat).
        :raises ValueError: If token is invalid or Yandex API rejects the request.
        """
        http = await self._get_http_client()
        url = f"{self.BASE_URL}/self/update/"

        try:
            resp = await http.post(
                url,
                json={"webhook_url": webhook_url},
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise ValueError(f"Network error registering webhook: {e}") from e

        if resp.status_code != 200:
            raise ValueError(
                f"Yandex API rejected webhook registration: {resp.status_code}"
            )

        result = resp.json()
        if not result.get("ok"):
            raise ValueError(
                f"Yandex webhook registration failed: "
                f"{result.get('description', 'unknown')}"
            )


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _build_suggest_buttons(
    buttons: list[list[dict]],
) -> dict[str, Any]:
    """Convert abstract button rows → Yandex SuggestButtons.

    Our format: [[{"text": "Label", "payload": "action"}], ...]
    Yandex format: {
        "layout": "true",
        "buttons": [[{"id": "...", "title": "...", "directives": [...]}], ...]
    }

    Each button gets a server_action directive so the bot receives
    bot_request.server_action on press.
    """
    rows: list[list[dict[str, Any]]] = []
    for row in buttons:
        yandex_row = []
        for btn in row:
            payload = btn.get("payload", btn["text"])
            yandex_row.append(
                {
                    "id": btn["text"],
                    "title": btn["text"],
                    "directives": [
                        {
                            "type": "server_action",
                            "name": btn["text"],
                            "payload": payload,
                        }
                    ],
                }
            )
        rows.append(yandex_row)

    return {
        "layout": "true",
        "buttons": rows,
    }


def _guess_mime_from_name(filename: str) -> str:
    """Guess MIME type from filename extension."""
    ext = Path(filename).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".ogg": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
    }
    return mime_map.get(ext, "application/octet-stream")
