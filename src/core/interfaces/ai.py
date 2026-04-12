"""Port: multimodal AI service interface."""

from abc import ABC, abstractmethod
from typing import Any


class AIServiceError(Exception):
    """Raised when AI service fails."""

    pass


class IMultiModalAI(ABC):
    """Port: interface for AI providers with vision + JSON output.

    Implementations use OpenAI-compatible API (OpenRouter, Google AI Studio, etc.).
    Vendor switching = changing ai_base_url + ai_api_key in config.

    Optimized for Gemma 4 (google/gemma-4-26b-a4b-it):
    - CoT via <|think|> token in system_prompt
    - Text-only and multimodal (vision) requests
    """

    @abstractmethod
    async def generate_json(
        self,
        system_prompt: str,
        text: str,
        image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send multimodal request, return strict JSON.

        :param system_prompt: System instruction. For CoT models (Gemma 4),
            prefix with <|think|> token to enable chain-of-thought reasoning.
        :param text: User message text.
        :param image_paths: Local paths to images for vision (optional).
            Pass None or [] for text-only requests.
        :returns: Parsed JSON dict from model response.
        :raises AIServiceError: On API failure, timeout, or invalid JSON response.
        """
        ...

    @abstractmethod
    async def generate_text(
        self,
        system_prompt: str,
        text: str,
        image_paths: list[str] | None = None,
    ) -> str:
        """Send multimodal request, return raw text.

        :param system_prompt: System instruction.
        :param text: User message text.
        :param image_paths: Local paths to images for vision (optional).
        :returns: Raw text response from model.
        :raises AIServiceError: On API failure or timeout.
        """
        ...
