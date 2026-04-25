"""OpenRouter AI adapter — Gemma 4 optimized.

Uses OpenAI-compatible chat/completions format via httpx.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from core.interfaces.ai import AIServiceError, IMultiModalAI
from infrastructure.messengers.base import BaseHttpAdapter

logger = logging.getLogger(__name__)

# Gemma 4 optimal generation parameters
GEMMA4_DEFAULT_PARAMS = {
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 64,
}

# CoT token for Gemma 4 thinking mode
COT_TOKEN = "<|think|>"

# Maximum file size for image encoding (10MB)
MAX_IMAGE_SIZE = 10 * 1024 * 1024


class OpenRouterAdapter(BaseHttpAdapter, IMultiModalAI):
    """OpenAI-compatible adapter optimized for Gemma 4 via OpenRouter.

    Key Gemma 4 specifics:
    1. temperature=1.0, top_p=0.95, top_k=64
    2. Images MUST precede text in content array
    3. System prompt prefixed with <|think|> for Chain-of-Thought
    4. response_format: json_object when available
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
        generation_params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(http_client, timeout=timeout)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._gen_params = generation_params or GEMMA4_DEFAULT_PARAMS

    # ──────────────────────────────────────────────
    # IMultiModalAI implementation
    # ──────────────────────────────────────────────

    async def generate_json(
        self,
        system_prompt: str,
        text: str,
        image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate strict JSON response."""
        messages = self._build_messages(system_prompt, text, image_paths)

        response = await self._call_api(
            messages=messages,
            json_mode=True,
        )

        content = self._extract_content(response)

        # Strip CoT thinking output if present
        content = self._strip_thinking(content)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise AIServiceError(f"Model returned invalid JSON: {content[:300]}") from e

    async def generate_text(
        self,
        system_prompt: str,
        text: str,
        image_paths: list[str] | None = None,
    ) -> str:
        """Generate raw text response."""
        messages = self._build_messages(system_prompt, text, image_paths)

        response = await self._call_api(
            messages=messages,
            json_mode=False,
        )

        content = self._extract_content(response)
        return self._strip_thinking(content)

    # ──────────────────────────────────────────────
    # Message construction (Gemma 4 specific)
    # ──────────────────────────────────────────────

    def _build_messages(
        self,
        system_prompt: str,
        text: str,
        image_paths: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Build OpenAI-format messages.

        Gemma 4 requirements:
        - System prompt prefixed with <|think|> for CoT
        - Images BEFORE text in content array
        """
        # CoT prefix for system prompt
        cot_prompt = f"{COT_TOKEN}{system_prompt}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": cot_prompt},
        ]

        # User message: multimodal or text-only
        if image_paths:
            content: list[dict[str, Any]] = []

            # GEMMA 4: images MUST come first
            for path in image_paths:
                b64 = self._encode_image(path)
                mime = self._guess_mime(path)
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    }
                )

            # Text AFTER images
            content.append({"type": "text", "text": text})

            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": text})

        return messages

    # ──────────────────────────────────────────────
    # API call
    # ──────────────────────────────────────────────

    async def _call_api(
        self,
        messages: list[dict[str, Any]],
        json_mode: bool = False,
    ) -> dict[str, Any]:
        """Call /chat/completions with Gemma 4 params."""
        http = await self._get_http_client()
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            **self._gen_params,  # temperature, top_p, top_k
        }

        if json_mode:
            body["response_format"] = {"type": "json_object"}

        logger.debug(
            "AI API call: model=%s, messages=%d, json_mode=%s",
            self._model,
            len(messages),
            json_mode,
        )

        # TODO: add retry layer for transient errors (429/502/503)
        # with exponential backoff (1-2 attempts, short delay)
        # to reduce full Celery retry cycles.

        try:
            resp = await http.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException as e:
            raise AIServiceError(f"AI API timeout after {self._timeout}s") from e
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:500]
            raise AIServiceError(
                f"AI API error {e.response.status_code}: {detail}"
            ) from e

    # ──────────────────────────────────────────────
    # Response parsing
    # ──────────────────────────────────────────────

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        """Extract text from chat completion response."""
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.warning("Unexpected API response: %s", list(response.keys()))
            raise AIServiceError("Unexpected API response structure") from e

    @staticmethod
    def _strip_thinking(content: str) -> str:
        """Remove Gemma 4 CoT thinking block from response.

        Gemma 4 with <|think|> wraps reasoning in `````` tags.
        The actual answer follows after the closing tag.
        If the closing tag is missing (model ran out of tokens), returns empty string.
        """
        think_end_tag = "</think>"
        think_start_tag = "<|think|>"
        if think_end_tag in content:
            return content.split(think_end_tag, 1)[-1].strip()
        if content.strip().startswith(think_start_tag):
            # Unclosed thinking — model ran out of tokens
            return ""
        return content

    # ──────────────────────────────────────────────
    # Image encoding
    # ──────────────────────────────────────────────

    @staticmethod
    def _encode_image(path: str) -> str:
        """Read and base64-encode a local image file."""
        file_path = Path(path)
        if not file_path.exists():
            raise AIServiceError(f"Image file not found: {path}")
        size = file_path.stat().st_size
        if size > MAX_IMAGE_SIZE:
            raise AIServiceError(
                f"Image file too large: {size} bytes (max {MAX_IMAGE_SIZE})"
            )
        return base64.b64encode(file_path.read_bytes()).decode("utf-8")

    @staticmethod
    def _guess_mime(path: str) -> str:
        """Guess MIME type from extension."""
        ext = Path(path).suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
        }
        return mime_map.get(ext, "application/octet-stream")
