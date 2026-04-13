"""Groq Whisper STT adapter — OpenAI-compatible API."""

import logging
from pathlib import Path

import httpx

from core.interfaces.speech import ISpeechToText, STTError

logger = logging.getLogger(__name__)

# Maximum audio file size (25MB — Groq limit)
MAX_AUDIO_SIZE = 25 * 1024 * 1024

# Supported MIME types for Groq Whisper
SUPPORTED_EXTENSIONS = {".ogg", ".mp3", ".wav", ".m4a", ".flac", ".webm", ".opus"}


class GroqWhisperAdapter(ISpeechToText):
    """Groq Cloud STT using Whisper-large-v3.

    Uses OpenAI-compatible /v1/audio/transcriptions endpoint.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.groq.com/openai/v1",
        model: str = "whisper-large-v3",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = http_client
        self._owns_client = http_client is None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy httpx client creation."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        """Close the underlying httpx client if we created it."""
        if self._owns_client and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def transcribe(self, file_path: str, language: str = "ru") -> str:
        """Transcribe audio file via Groq Whisper API.

        :param file_path: Local path to audio file.
        :param language: ISO 639-1 language code.
        :returns: Transcribed text.
        :raises STTError: On API failure or invalid file.
        """
        path = Path(file_path)

        # Validate file
        if not path.exists():
            raise STTError(f"Audio file not found: {file_path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise STTError(f"Unsupported audio format: {path.suffix}")
        size = path.stat().st_size
        if size > MAX_AUDIO_SIZE:
            raise STTError(f"Audio file too large: {size} bytes (max {MAX_AUDIO_SIZE})")

        http = await self._get_http_client()
        url = f"{self._base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        with open(path, "rb") as f:
            files = {"file": (path.name, f)}
            data = {
                "model": self._model,
                "language": language,
                "response_format": "text",
            }

            try:
                resp = await http.post(url, headers=headers, files=files, data=data)
                resp.raise_for_status()
                return resp.text.strip()
            except httpx.TimeoutException as e:
                raise STTError(f"STT API timeout after {self._timeout}s") from e
            except httpx.HTTPStatusError as e:
                detail = e.response.text[:500]
                raise STTError(
                    f"STT API error {e.response.status_code}: {detail}"
                ) from e
