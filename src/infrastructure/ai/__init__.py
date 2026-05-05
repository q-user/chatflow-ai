"""AI adapter factory."""

from core.interfaces.ai import IMultiModalAI  # noqa: F401
from infrastructure.ai.adapter import OpenRouterAdapter
from infrastructure.config import settings


def create_ai_adapter(provider_id: str | None = None) -> IMultiModalAI:
    """Create AI adapter from provider registry or application settings.

    :param provider_id: Key from SUPPORTED_AI_PROVIDERS (e.g. "google_gemini_flash").
                        If None, uses the default provider.
    """
    from infrastructure.ai.registry import SUPPORTED_AI_PROVIDERS

    if provider_id is None:
        provider_id = "google_gemini_flash"

    cfg = SUPPORTED_AI_PROVIDERS.get(provider_id)
    if not cfg:
        raise ValueError(f"Unknown provider_id: {provider_id}")

    key = getattr(settings, cfg["key_env"], None)
    if not key:
        raise ValueError(
            f"API key for {provider_id} is not set. "
            f"Configure {cfg['key_env']} in .env or environment."
        )

    return OpenRouterAdapter(
        api_key=key,
        base_url=cfg["base_url"],
        model=cfg["model"],
        timeout=settings.ai_timeout,
    )


__all__ = ["create_ai_adapter", "OpenRouterAdapter"]
