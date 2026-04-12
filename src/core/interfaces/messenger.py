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
    async def send_text(self, chat_id: str, text: str) -> None:
        """Send a text message.

        :param chat_id: Target chat ID.
        :param text: Message text.
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
