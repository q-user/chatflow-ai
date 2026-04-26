"""STT adapter factory."""

from core.interfaces.speech import ISpeechToText  # noqa: F401
from infrastructure.config import settings
from infrastructure.stt.whisper import GroqWhisperAdapter


def create_stt_adapter() -> ISpeechToText:
    """Create STT adapter from application settings."""
    if not settings.stt_api_key:
        raise ValueError("STT_API_KEY is not set. Configure it in .env or environment.")
    return GroqWhisperAdapter(
        api_key=settings.stt_api_key,
        base_url=settings.stt_base_url,
        model=settings.stt_model_name,
    )


__all__ = ["create_stt_adapter", "GroqWhisperAdapter"]
