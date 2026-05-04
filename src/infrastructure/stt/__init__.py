"""STT adapter factory."""

from core.interfaces.speech import ISpeechToText  # noqa: F401
from infrastructure.config import settings
from infrastructure.stt.riva import NvidiaRivaAdapter
from infrastructure.stt.whisper import GroqWhisperAdapter

_STT_PROVIDERS = {"groq", "riva"}


def create_stt_adapter() -> ISpeechToText:
    """Create STT adapter based on ``settings.stt_provider``.

    Supported providers: ``"groq"`` (default), ``"riva"``.
    """
    provider = settings.stt_provider

    if provider not in _STT_PROVIDERS:
        raise ValueError(
            f"Unknown STT provider: {provider!r}. Choose from: {', '.join(sorted(_STT_PROVIDERS))}"
        )

    if provider == "riva":
        if not settings.nvidia_api_key:
            raise ValueError(
                "NVIDIA_API_KEY is not set. Configure it in .env or environment."
            )
        return NvidiaRivaAdapter(
            api_key=settings.nvidia_api_key,
            server_url=settings.riva_server_url,
            function_id=settings.riva_function_id,
        )

    if not settings.stt_api_key:
        raise ValueError("STT_API_KEY is not set. Configure it in .env or environment.")
    return GroqWhisperAdapter(
        api_key=settings.stt_api_key,
        base_url=settings.stt_base_url,
        model=settings.stt_model_name,
    )


__all__ = ["create_stt_adapter", "GroqWhisperAdapter", "NvidiaRivaAdapter"]
