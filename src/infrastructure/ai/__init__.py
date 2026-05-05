"""AI adapter factory."""

from core.interfaces.ai import IMultiModalAI  # noqa: F401
from infrastructure.ai.adapter import OpenRouterAdapter
from infrastructure.config import settings


def create_ai_adapter(
    provider_id: str | None = None, model_id: str | None = None
) -> IMultiModalAI:
    """Create AI adapter from provider registry or application settings.

    :param provider_id: Key from AI_PROVIDERS (e.g. "google").
                        If None, uses the default provider.
    :param model_id: Specific model id from provider's models list.
                      If None, uses the first model in the provider config.
    """
    from infrastructure.ai.registry import AI_PROVIDERS

    if provider_id is None:
        provider_id = "google"

    cfg = AI_PROVIDERS.get(provider_id)
    if not cfg:
        raise ValueError(f"Unknown provider_id: {provider_id}")

    if model_id is None:
        model_id = cfg["models"][0]["id"]

    key = getattr(settings, cfg["key_field"], None)
    if not key:
        raise ValueError(
            f"API key for {provider_id} is not set. "
            f"Configure {cfg['key_field']} in .env or environment."
        )

    return OpenRouterAdapter(
        api_key=key,
        base_url=cfg["base_url"],
        model=model_id,
        timeout=settings.ai_timeout,
    )


__all__ = ["create_ai_adapter", "OpenRouterAdapter"]
