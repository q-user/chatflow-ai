"""Yandex Messenger Bot API adapter via httpx."""

import httpx

from core.domain.incoming import IncomingEnvelope
from core.interfaces.messenger import IMessengerAdapter
from infrastructure.messengers.base import BaseHttpAdapter


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

    # ── Implemented ──────────────────────────────

    async def send_text(self, chat_id: str, text: str, buttons=None) -> None:
        http = await self._get_http_client()
        url = f"{self.BASE_URL}/messages/sendText/"
        payload = {"chat_id": chat_id, "text": text}
        try:
            resp = await http.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
        except httpx.RequestError as e:
            raise ValueError(f"Network error sending text message: {e}") from e

    # ── Stubs ─────────────────────────────────────

    async def parse_webhook(self, payload: dict, bot_token: str) -> IncomingEnvelope:
        raise NotImplementedError("YandexAdapter.parse_webhook not yet implemented")

    async def send_file(self, chat_id: str, file_path: str, caption=None) -> None:
        raise NotImplementedError("YandexAdapter.send_file not yet implemented")

    async def download_file(self, file_id: str, dest_path: str) -> str:
        raise NotImplementedError("YandexAdapter.download_file not yet implemented")

    async def register_webhook(self, webhook_url: str) -> None:
        raise NotImplementedError("YandexAdapter.register_webhook not yet implemented")
