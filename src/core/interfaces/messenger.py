"""Port: messenger adapter interface (Clean Architecture boundary)."""

from abc import ABC, abstractmethod

from core.domain.incoming import IncomingEnvelope


class IMessengerAdapter(ABC):
    """Port: interface for messenger adapters.

    Concrete implementations live in infrastructure/ (e.g. TelegramAdapter,
    YandexAdapter). The core application depends only on this abstraction.
    """

    @abstractmethod
    async def parse_webhook(self, payload: dict, bot_token: str) -> IncomingEnvelope:
        """Parse raw webhook payload into an IncomingEnvelope.

        :param payload: Raw dict from messenger webhook.
        :param bot_token: Bot API token for this instance.
        :returns: Parsed IncomingEnvelope.
        :raises ValueError: If payload structure is invalid.
        """
        ...

    @abstractmethod
    async def send_text(
        self,
        chat_id: str,
        text: str,
        buttons: list[list[dict]] | None = None,
    ) -> None:
        """Send a text message.

        :param chat_id: Target chat ID.
        :param text: Message text.
        :param buttons: Optional inline keyboard rows.
            Each row is a list of button dicts:
            {"text": "Label", "payload": "action_name"}
            If None — no keyboard (plain text message).
        """
        ...

    @abstractmethod
    async def send_file(
        self, chat_id: str, file_path: str, caption: str | None = None
    ) -> None:
        """Send a file.

        :param chat_id: Target chat ID.
        :param file_path: Local path to the file.
        :param caption: Optional caption.
        """
        ...

    @abstractmethod
    async def download_file(self, file_id: str, dest_path: str) -> str:
        """Download a file from the messenger.

        :param file_id: File ID from the messenger.
        :param dest_path: Local destination path.
        :returns: Path to the saved file.
        """
        ...

    async def answer_callback(self, callback_id: str) -> None:
        """Acknowledge callback query (no-op by default).

        Override in adapters that support callback queries (e.g. Telegram).
        """
        pass  # default: no-op

    async def register_webhook(
        self, webhook_url: str, secret: str | None = None
    ) -> None:
        """Register a webhook URL with the messenger platform.

        :param webhook_url: Full public URL for the webhook endpoint.
        :param secret: Optional webhook secret (e.g. MAX X-Max-Bot-Api-Secret).
        :raises ValueError: If token is invalid or platform rejects the request.
        """
        pass  # default: no-op — override in adapters that support it

    async def aclose(self) -> None:
        """Release underlying resources (HTTP connections, etc.).

        No-op by default. Override in adapters that manage their own clients.
        """
        pass  # default: no-op
