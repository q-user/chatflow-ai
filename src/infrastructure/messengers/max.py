"""MAX (eXpress) Messenger Bot API adapter via httpx.

API docs: https://dev.max.ru/docs-api
Auth: Authorization: <token> header (NO Bearer prefix)

Webhook payload structure (Update):
  message_created:
    {
      "update_type": "message_created",
      "timestamp": N,
      "message": {
        "sender": {"user_id": N, "name": "...", "username": "..."},
        "recipient": {"chat_id": N, "user_id": N},
        "body": {"mid": "...", "text": "...", "attachments": [...]},
        "timestamp": N
      }
    }

  message_callback:
    {
      "update_type": "message_callback",
      "timestamp": N,
      "callback": {
        "callback_id": "...",
        "payload": "...",
        "user": {"user_id": N, ...},
        "chat": {"chat_id": N}
      }
    }

Key differences from Telegram:
  - Auth via header (not URL token)
  - Buttons are attachments (inline_keyboard), not reply_markup
  - File sending is 2-step: upload → attach by token
  - File download: URL comes directly in webhook attachment payload
  - Callback uses message_callback with callback_id (answerable via /answers)
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx

from core.domain.incoming import IncomingEnvelope
from core.interfaces.messenger import IMessengerAdapter
from infrastructure.messengers.base import BaseHttpAdapter

logger = logging.getLogger(__name__)


class MaxAdapter(BaseHttpAdapter, IMessengerAdapter):
    """MAX (eXpress) Messenger Bot API adapter.

    API docs: https://dev.max.ru/docs-api
    Auth: Authorization: <token> header
    """

    BASE_URL = "https://platform-api.max.ru"

    def __init__(self, bot_token: str, http_client: httpx.AsyncClient | None = None):
        super().__init__(http_client)
        self._bot_token = bot_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._bot_token}

    # ──────────────────────────────────────────────
    # IMessengerAdapter implementation
    # ──────────────────────────────────────────────

    async def parse_webhook(self, payload: dict, bot_token: str) -> IncomingEnvelope:
        """Parse MAX Update object → IncomingEnvelope.

        Handles:
        - message_callback (button press)
        - message_created (text / file messages)

        :param payload: Raw MAX webhook payload (Update object).
        :param bot_token: Bot token (unused, kept for interface compat).
        :returns: Parsed IncomingEnvelope.
        :raises ValueError: If payload structure is invalid.
        """
        update_type = payload.get("update_type")
        if not update_type:
            raise ValueError("No update_type in MAX webhook payload")

        # 1. Handle callback (button press)
        if update_type == "message_callback":
            return self._parse_callback(payload)

        # 2. Handle text/file message
        if update_type == "message_created":
            return self._parse_message(payload)

        # 3. Ignore other update types (bot_started, chat_created, etc.)
        # Return a minimal envelope — the router will discard it
        raise ValueError(f"Unsupported MAX update_type: {update_type}")

    def _parse_callback(self, payload: dict) -> IncomingEnvelope:
        """Parse message_callback update."""
        callback = payload.get("callback", {})
        user = callback.get("user", {})
        chat = callback.get("chat", {})

        messenger_user_id = str(user.get("user_id", ""))
        chat_id = (
            str(chat.get("chat_id", "")) if chat.get("chat_id") else messenger_user_id
        )
        callback_id = str(callback.get("callback_id", ""))
        callback_payload = str(callback.get("payload", ""))

        return IncomingEnvelope(
            messenger_user_id=messenger_user_id,
            chat_id=chat_id,
            text=callback_payload,
            bot_instance_id=uuid.uuid4(),  # placeholder — set by router
            messenger_type="MX",
            is_callback=True,
            raw_callback_id=callback_id,
        )

    def _parse_message(self, payload: dict) -> IncomingEnvelope:
        """Parse message_created update."""
        message = payload.get("message", {})
        sender = message.get("sender", {})
        recipient = message.get("recipient", {})
        body = message.get("body", {})

        messenger_user_id = str(sender.get("user_id", ""))
        if not messenger_user_id:
            raise ValueError("No sender.user_id in MAX message")

        chat_id = (
            str(recipient.get("chat_id", ""))
            if recipient.get("chat_id")
            else messenger_user_id
        )

        text = body.get("text")

        file_id, file_type, file_name = self._extract_file_attachment(
            body.get("attachments") or []
        )

        return IncomingEnvelope(
            messenger_user_id=messenger_user_id,
            chat_id=chat_id,
            text=text,
            file_id=file_id,
            file_type=file_type,
            file_name=file_name,
            bot_instance_id=uuid.uuid4(),
            messenger_type="MX",
        )

    @staticmethod
    def _extract_file_attachment(
        attachments: list[dict],
    ) -> tuple[str | None, str | None, str | None]:
        """Extract first file attachment from MAX attachments list."""
        for att in attachments:
            att_type = att.get("type", "")
            att_payload = att.get("payload", {})
            if att_type not in ("image", "file", "video", "audio", "voice"):
                continue
            file_url = att_payload.get("url")
            if not file_url:
                continue
            file_name = att_payload.get("filename") or att_payload.get("name")
            if att_type == "image":
                return file_url, "image/jpeg", file_name
            if att_type == "video":
                return file_url, "video/mp4", file_name
            if att_type in ("audio", "voice"):
                mime = att_payload.get("mime_type") or "audio/ogg"
                return file_url, mime, file_name
            mime = att_payload.get("mime_type", "application/octet-stream")
            return file_url, mime, file_name or "document"
        return None, None, None

    async def send_text(
        self,
        chat_id: str,
        text: str,
        buttons: list[list[dict]] | None = None,
    ) -> None:
        """Send a text message via POST /messages.

        :param chat_id: Target chat ID (or user_id for DMs).
        :param text: Message text (up to 4000 chars).
        :param buttons: Optional inline keyboard rows.
            Each row is a list of button dicts:
            {"text": "Label", "payload": "action_name"}
            Converted to MAX inline_keyboard attachment.
        :raises ValueError: If network error occurs.
        """
        http = await self._get_http_client()
        url = f"{self.BASE_URL}/messages"

        body: dict[str, Any] = {"text": text}
        params: dict[str, str] = {}

        # Determine if chat_id or user_id
        if chat_id.lstrip("-").isdigit() and len(chat_id) > 8:
            # Looks like a group chat_id (negative or large number)
            params["chat_id"] = chat_id
        else:
            params["user_id"] = chat_id

        if buttons:
            body["attachments"] = [_build_inline_keyboard(buttons)]

        try:
            resp = await http.post(
                url, params=params, json=body, headers=self._headers()
            )
            resp.raise_for_status()
        except httpx.RequestError as e:
            raise ValueError(f"Network error sending text message: {e}") from e

    async def send_file(
        self, chat_id: str, file_path: str, caption: str | None = None
    ) -> None:
        """Send a file via 2-step upload flow.

        Step 1: POST /uploads?type=file → get upload URL
        Step 2: Upload file to the URL → get token
        Step 3: POST /messages with file attachment

        :param chat_id: Target chat ID.
        :param file_path: Local path to the file.
        :param caption: Optional caption (sent as separate text before file).
        :raises ValueError: If network error or upload fails.
        """
        http = await self._get_http_client()

        # Step 1: Get upload URL
        try:
            uploads_resp = await http.post(
                f"{self.BASE_URL}/uploads",
                params={"type": "file"},
                headers=self._headers(),
            )
            uploads_resp.raise_for_status()
            upload_data = uploads_resp.json()
            upload_url = upload_data["url"]
        except httpx.RequestError as e:
            raise ValueError(f"Network error getting upload URL: {e}") from e
        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid upload URL response: {e}") from e

        # Step 2: Upload file to the URL
        try:
            with open(file_path, "rb") as f:
                upload_resp = await http.post(
                    upload_url,
                    files={"data": (Path(file_path).name, f)},
                )
                upload_resp.raise_for_status()
                file_token = upload_resp.json().get("token")
                if not file_token:
                    raise ValueError("No token in upload response")
        except httpx.RequestError as e:
            raise ValueError(f"Network error uploading file: {e}") from e

        # Step 3: Send message with file attachment
        # Retry on attachment.not.ready (file processing delay)
        msg_body: dict[str, Any] = {
            "text": caption or Path(file_path).name,
            "attachments": [{"type": "file", "payload": {"token": file_token}}],
        }
        params: dict[str, str] = {}
        if chat_id.lstrip("-").isdigit() and len(chat_id) > 8:
            params["chat_id"] = chat_id
        else:
            params["user_id"] = chat_id

        for attempt in range(3):
            try:
                resp = await http.post(
                    f"{self.BASE_URL}/messages",
                    params=params,
                    json=msg_body,
                    headers=self._headers(),
                )
                if resp.status_code == 400:
                    err = resp.json()
                    if err.get("code") == "attachment.not.ready":
                        logger.warning("File not ready yet, retry %d/3", attempt + 1)
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                resp.raise_for_status()
                return
            except httpx.RequestError as e:
                raise ValueError(f"Network error sending file message: {e}") from e

        raise ValueError("File attachment not ready after 3 retries")

    async def download_file(self, file_id: str, dest_path: str) -> str:
        """Download a file by URL.

        MAX sends direct URLs in attachment payloads.
        file_id in our IncomingEnvelope IS the download URL.

        :param file_id: Direct URL to the file.
        :param dest_path: Local destination path.
        :returns: Path to the saved file.
        :raises ValueError: If network error occurs.
        """
        http = await self._get_http_client()

        try:
            resp = await http.get(file_id, headers=self._headers())
            resp.raise_for_status()

            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return str(dest)
        except httpx.RequestError as e:
            raise ValueError(f"Network error downloading file: {e}") from e

    async def register_webhook(
        self, webhook_url: str, secret: str | None = None
    ) -> None:
        """Register a webhook via POST /subscriptions.

        :param webhook_url: Full public HTTPS URL for the webhook endpoint.
        :param secret: Webhook secret for X-Max-Bot-Api-Secret verification.
        :raises ValueError: If token is invalid or MAX API rejects the request.
        """
        http = await self._get_http_client()
        url = f"{self.BASE_URL}/subscriptions"

        body: dict[str, Any] = {
            "url": webhook_url,
            "update_types": ["message_created", "message_callback"],
        }
        if secret:
            body["secret"] = secret

        try:
            resp = await http.post(url, json=body, headers=self._headers())
        except httpx.RequestError as e:
            raise ValueError(f"Network error registering webhook: {e}") from e

        if resp.status_code != 200:
            raise ValueError(
                f"MAX API rejected webhook registration: {resp.status_code}"
            )

        result = resp.json()
        if not result.get("success"):
            raise ValueError(
                f"MAX webhook registration failed: {result.get('message', 'unknown')}"
            )

    async def answer_callback(self, callback_id: str) -> None:
        """Acknowledge callback query via POST /answers.

        :param callback_id: MAX callback_id from message_callback update.
        :raises ValueError: If network error occurs.
        """
        http = await self._get_http_client()
        url = f"{self.BASE_URL}/answers"

        try:
            resp = await http.post(
                url,
                params={"callback_id": callback_id},
                json={"notification": "OK"},
                headers=self._headers(),
            )
            resp.raise_for_status()
        except httpx.RequestError as e:
            raise ValueError(f"Network error answering callback: {e}") from e


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _build_inline_keyboard(
    buttons: list[list[dict]],
) -> dict[str, Any]:
    """Convert abstract button rows → MAX inline_keyboard attachment.

    Our format: [[{"text": "Label", "payload": "action"}], ...]
    MAX format: {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [[{"type": "callback", "text": "...", "payload": "..."}], ...]
        }
    }
    """
    rows: list[list[dict[str, Any]]] = []
    for row in buttons:
        max_row = []
        for btn in row:
            payload = btn.get("payload", btn["text"])
            max_row.append(
                {
                    "type": "callback",
                    "text": btn["text"],
                    "payload": payload,
                }
            )
        rows.append(max_row)

    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": rows,
        },
    }
