"""Telegram Bot API adapter via httpx."""

import uuid
from pathlib import Path
from typing import Any

import httpx

from core.domain.incoming import IncomingEnvelope
from core.interfaces.messenger import IMessengerAdapter


class TelegramAdapter(IMessengerAdapter):
    """Telegram Bot API adapter via httpx.

    Implements the IMessengerAdapter port for Telegram messenger.
    Each instance is bound to a specific bot token.
    """

    BASE_URL = "https://api.telegram.org/bot{token}"
    FILE_URL = "https://api.telegram.org/file/bot{token}/{file_path}"

    def __init__(
        self,
        bot_token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._http: httpx.AsyncClient | None = http_client
        self._owns_client = http_client is None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy httpx client creation."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def aclose(self) -> None:
        """Close the underlying httpx client if we created it."""
        if self._owns_client and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ──────────────────────────────────────────────
    # IMessengerAdapter implementation
    # ──────────────────────────────────────────────

    async def parse_webhook(self, payload: dict, bot_token: str) -> IncomingEnvelope:
        """Parse Telegram Update object → IncomingEnvelope.

        Handles: callback_query, text messages, documents, photos, captions.
        bot_instance_id is set to placeholder — the router injects the real value.

        :param payload: Raw Telegram webhook payload (Update object).
        :param bot_token: Bot API token (used for validation).
        :returns: Parsed IncomingEnvelope.
        :raises ValueError: If payload has no message or callback_query.
        """
        # 1. Check callback_query FIRST (priority over message)
        if "callback_query" in payload:
            cq = payload["callback_query"]
            return IncomingEnvelope(
                messenger_user_id=str(cq["from"]["id"]),
                chat_id=str(cq["message"]["chat"]["id"]),
                text=cq["data"],  # button payload → text
                bot_instance_id=uuid.uuid4(),
                messenger_type="TG",
                is_callback=True,
                raw_callback_id=str(cq["id"]),
            )

        # 2. Existing logic for message / edited_message
        message = payload.get("message") or payload.get("edited_message", {})
        if not message:
            raise ValueError("No message or callback_query in webhook payload")

        chat_id = str(message["chat"]["id"])
        messenger_user_id = str(message["from"]["id"])

        # Extract text — caption serves as text for file messages
        text = message.get("text") or message.get("caption")

        # Extract file info
        file_id: str | None = None
        file_type: str | None = None
        file_name: str | None = None

        if "document" in message:
            doc = message["document"]
            file_id = doc["file_id"]
            file_type = doc.get("mime_type")
            file_name = doc.get("file_name")
        elif "photo" in message:
            # Telegram sends array of PhotoSize — last is largest
            photo = message["photo"][-1]
            file_id = photo["file_id"]
            file_type = "image/jpeg"  # Telegram photos are always JPEG

        return IncomingEnvelope(
            messenger_user_id=messenger_user_id,
            chat_id=chat_id,
            text=text,
            file_id=file_id,
            file_type=file_type,
            file_name=file_name,
            bot_instance_id=uuid.uuid4(),  # placeholder — set by router
            messenger_type="TG",
        )

    async def send_text(
        self,
        chat_id: str,
        text: str,
        buttons: list[list[dict]] | None = None,
    ) -> None:
        """Send a text message via /sendMessage.

        :param chat_id: Target chat ID.
        :param text: Message text.
        :param buttons: Optional inline keyboard rows.
        :raises httpx.HTTPStatusError: If API returns an error.
        """
        http = await self._get_http_client()
        url = self.BASE_URL.format(token=self._bot_token) + "/sendMessage"

        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        if buttons:
            keyboard = [
                [{"text": btn["text"], "callback_data": btn["payload"]} for btn in row]
                for row in buttons
            ]
            body["reply_markup"] = {"inline_keyboard": keyboard}

        response = await http.post(url, json=body)
        response.raise_for_status()

    async def send_file(
        self, chat_id: str, file_path: str, caption: str | None = None
    ) -> None:
        """Send a file via /sendDocument.

        :param chat_id: Target chat ID.
        :param file_path: Local path to the file.
        :param caption: Optional caption.
        :raises httpx.HTTPStatusError: If API returns an error.
        """
        http = await self._get_http_client()
        url = self.BASE_URL.format(token=self._bot_token) + "/sendDocument"
        with open(file_path, "rb") as f:
            files = {"document": (Path(file_path).name, f)}
            data: dict[str, Any] = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            response = await http.post(url, data=data, files=files)
        response.raise_for_status()

    async def download_file(self, file_id: str, dest_path: str) -> str:
        """Download a file from Telegram.

        Two-step process:
        1. GET /getFile → get file_path
        2. GET file_url → download content → save to dest_path

        :param file_id: Telegram file ID.
        :param dest_path: Local destination path.
        :returns: Path to the saved file.
        :raises httpx.HTTPStatusError: If API returns an error.
        """
        http = await self._get_http_client()
        # Step 1: Get file path from Telegram
        get_file_url = self.BASE_URL.format(token=self._bot_token) + "/getFile"
        response = await http.get(get_file_url, params={"file_id": file_id})
        response.raise_for_status()
        tg_file_path = response.json()["result"]["file_path"]

        # Step 2: Download the file
        file_url = self.FILE_URL.format(token=self._bot_token, file_path=tg_file_path)
        download_response = await http.get(file_url)
        download_response.raise_for_status()

        # Step 3: Save to dest_path
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(download_response.content)
        return str(dest)

    async def answer_callback(self, callback_id: str) -> None:
        """Answer callback query to dismiss loading state on button.

        :param callback_id: Telegram callback_query ID.
        """
        http = await self._get_http_client()
        url = self.BASE_URL.format(token=self._bot_token) + "/answerCallbackQuery"
        response = await http.post(url, json={"callback_query_id": callback_id})
        response.raise_for_status()
