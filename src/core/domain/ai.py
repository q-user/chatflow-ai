"""AI response domain entity."""

from typing import Any

from pydantic import BaseModel


class AIResponse(BaseModel):
    """Structured AI response wrapper."""

    raw_text: str
    parsed_json: dict[str, Any] | None = None
    model: str
    usage: dict[str, int] | None = (
        None  # {"prompt_tokens": ..., "completion_tokens": ...}
    )
