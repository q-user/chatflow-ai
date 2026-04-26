"""AI adapter factory."""

from core.interfaces.ai import IMultiModalAI  # noqa: F401
from infrastructure.ai.adapter import OpenRouterAdapter
from infrastructure.config import settings


def create_ai_adapter() -> IMultiModalAI:
    """Create AI adapter from application settings."""
    if not settings.ai_api_key:
        raise ValueError("AI_API_KEY is not set. Configure it in .env or environment.")
    return OpenRouterAdapter(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        model=settings.ai_model_name,
    )


__all__ = ["create_ai_adapter", "OpenRouterAdapter"]
