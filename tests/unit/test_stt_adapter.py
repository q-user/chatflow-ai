"""Unit tests for GroqWhisperAdapter (STT)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core.interfaces.speech import STTError
from infrastructure.stt.whisper import GroqWhisperAdapter


@pytest.fixture
def adapter() -> GroqWhisperAdapter:
    """Create GroqWhisperAdapter with mock HTTP client."""
    return GroqWhisperAdapter(api_key="test_api_key")


@pytest.fixture
def mock_http_response() -> MagicMock:
    """Mock successful HTTP response."""
    resp = MagicMock()
    resp.text = "Привет мир это тестовая транскрипция"
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def valid_audio_file(tmp_path) -> str:
    """Create a fake valid audio file."""
    audio_file = tmp_path / "test.ogg"
    audio_file.write_bytes(b"fake_audio_data")
    return str(audio_file)


@pytest.fixture
def large_audio_file(tmp_path) -> str:
    """Create a fake audio file exceeding 25MB."""
    audio_file = tmp_path / "large.ogg"
    audio_file.write_bytes(b"x" * (26 * 1024 * 1024))  # 26MB
    return str(audio_file)


# ──────────────────────────────────────────────
# transcribe — validation tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_file_not_found(adapter: GroqWhisperAdapter):
    """Non-existent file → STTError."""
    with pytest.raises(STTError, match="Audio file not found"):
        await adapter.transcribe("/nonexistent/file.ogg")


@pytest.mark.asyncio
async def test_transcribe_unsupported_format(adapter: GroqWhisperAdapter, tmp_path):
    """Unsupported file extension → STTError."""
    audio_file = tmp_path / "test.mp4"
    audio_file.write_bytes(b"fake_data")
    with pytest.raises(STTError, match="Unsupported audio format"):
        await adapter.transcribe(str(audio_file))


@pytest.mark.asyncio
async def test_transcribe_file_too_large(
    adapter: GroqWhisperAdapter, large_audio_file: str
):
    """File > 25MB → STTError."""
    with pytest.raises(STTError, match="Audio file too large"):
        await adapter.transcribe(large_audio_file)


# ──────────────────────────────────────────────
# transcribe — API call tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_success(
    adapter: GroqWhisperAdapter, valid_audio_file: str, mock_http_response
):
    """Valid audio file → transcribed text."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_http_response)
    adapter._http = mock_client

    result = await adapter.transcribe(valid_audio_file, language="ru")

    assert result == "Привет мир это тестовая транскрипция"
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    assert "file" in call_kwargs["files"]
    assert call_kwargs["data"]["model"] == "whisper-large-v3"
    assert call_kwargs["data"]["language"] == "ru"
    assert call_kwargs["data"]["response_format"] == "text"
    assert "Authorization" in call_kwargs["headers"]


@pytest.mark.asyncio
async def test_transcribe_api_timeout(
    adapter: GroqWhisperAdapter, valid_audio_file: str
):
    """API timeout → STTError."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    adapter._http = mock_client

    with pytest.raises(STTError, match="STT API timeout"):
        await adapter.transcribe(valid_audio_file)


@pytest.mark.asyncio
async def test_transcribe_api_error(adapter: GroqWhisperAdapter, valid_audio_file: str):
    """HTTP error → STTError with details."""
    error_resp = MagicMock()
    error_resp.status_code = 429
    error_resp.text = "Rate limit exceeded"
    http_error = httpx.HTTPStatusError(
        "Rate limited", request=MagicMock(), response=error_resp
    )
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=http_error)
    adapter._http = mock_client

    with pytest.raises(STTError, match="STT API error 429"):
        await adapter.transcribe(valid_audio_file)


@pytest.mark.asyncio
async def test_transcribe_empty_result(
    adapter: GroqWhisperAdapter, valid_audio_file: str
):
    """Empty transcription → returns empty string (not an error)."""
    mock_resp = MagicMock()
    mock_resp.text = "   "
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    adapter._http = mock_client

    result = await adapter.transcribe(valid_audio_file)
    assert result == ""


# ──────────────────────────────────────────────
# aclose tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aclose_owns_client():
    """aclose() closes httpx client when adapter owns it."""
    mock_client = AsyncMock()
    # When no http_client is passed, adapter owns the client it creates lazily
    adapter = GroqWhisperAdapter(api_key="key")
    # Manually set an owned client to test the close behavior
    adapter._http = mock_client
    adapter._owns_client = True
    await adapter.aclose()
    mock_client.aclose.assert_awaited_once()
    assert adapter._http is None


@pytest.mark.asyncio
async def test_aclose_does_not_close_external_client():
    """aclose() does NOT close external httpx client."""
    mock_client = AsyncMock()
    adapter = GroqWhisperAdapter(api_key="key", http_client=mock_client)
    await adapter.aclose()
    mock_client.aclose.assert_not_awaited()
    assert adapter._http is mock_client  # still there


def test_create_stt_adapter():
    """create_stt_adapter returns GroqWhisperAdapter when stt_provider='groq'."""
    from unittest.mock import patch

    with patch("infrastructure.stt.settings") as mock_settings:
        mock_settings.stt_provider = "groq"
        mock_settings.stt_api_key = "test_key"
        mock_settings.stt_base_url = "https://api.groq.com/openai/v1"
        mock_settings.stt_model_name = "whisper-large-v3"

        from infrastructure.stt import create_stt_adapter

        adapter = create_stt_adapter()

        from infrastructure.stt.whisper import GroqWhisperAdapter

        assert isinstance(adapter, GroqWhisperAdapter)
        assert adapter._api_key == "test_key"
        assert adapter._model == "whisper-large-v3"
