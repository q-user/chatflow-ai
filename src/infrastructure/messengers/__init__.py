"""Messenger adapter registry and factory."""

from core.interfaces.messenger import IMessengerAdapter
from infrastructure.messengers.telegram import TelegramAdapter


class UnsupportedMessengerError(ValueError):
    """Raised when a messenger type has no registered adapter."""

    pass


# Registry: messenger_type → adapter class
ADAPTER_REGISTRY: dict[str, type[IMessengerAdapter]] = {
    "TG": TelegramAdapter,
    # "YM": YandexAdapter,  # future
}


def create_adapter(messenger_type: str, bot_token: str) -> IMessengerAdapter:
    """Create a messenger adapter by type and bot token.

    :param messenger_type: "TG", "YM", etc.
    :param bot_token: Bot API token for this instance.
    :returns: Configured adapter instance.
    :raises UnsupportedMessengerError: If messenger_type is not registered.
    """
    adapter_cls = ADAPTER_REGISTRY.get(messenger_type)
    if adapter_cls is None:
        raise UnsupportedMessengerError(
            f"No adapter registered for messenger_type: {messenger_type}"
        )
    return adapter_cls(bot_token=bot_token)  # ty: ignore[unknown-argument]
