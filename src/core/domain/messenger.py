"""Shared constants for messenger type mappings.

Used across OTPService, MessengerLinkService, and HookRouterService
to avoid duplicating the messenger_type → column_name mapping.
"""

from typing import Literal

# Maps messenger_type (from webhook) to UserTable column name for linking
MESSENGER_TYPE_TO_FIELD: dict[str, str] = {
    "TG": "telegram_id",
    "YM": "yandex_id",
}

MessengerType = Literal["TG", "YM"]
