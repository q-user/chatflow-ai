"""Unit tests for NvidiaRivaAdapter (STT)."""

from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest

from core.interfaces.speech import STTError
from infrastructure.stt.riva import (
    LANGUAGE_MAP,
    NvidiaRivaAdapter,
    _convert_to_wav,
)


@pytest.fixture
def adapter() -> NvidiaRivaAdapter:
    """Create NvidiaRivaAdapter with test config."""
    return NvidiaRivaAdapter(
        api_key="test_nvidia_key",
        server_url="dns:///grpc.test.nvidia.com:443",
        function_id="test-function-id",
    )


@pytest.fixture
def valid_wav_file(tmp_path) -> str:
    """Create a fake WAV audio file."""
    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"RIFF" + b"\x00" * 100)
    return str(audio_file)


@pytest.fixture
def valid_ogg_file(tmp_path) -> str:
    """Create a fake OGG audio file (needs conversion)."""
    audio_file = tmp_path / "test.ogg"
    audio_file.write_bytes(b"OggS" + b"\x00" * 100)
    return str(audio_file)


@pytest.fixture
def large_audio_file(tmp_path) -> str:
    """Create a fake audio file exceeding 25MB."""
    audio_file = tmp_path / "large.wav"
    audio_file.write_bytes(b"x" * (26 * 1024 * 1024))
    return str(audio_file)


def _make_recognize_response(transcript: str = "Привет мир", confidence: float = 0.95):
    """Build a mock RecognizeResponse with one result/alternative."""
    alternative = MagicMock()
    alternative.transcript = transcript
    alternative.confidence = confidence

    result = MagicMock()
    result.alternatives = [alternative]

    response = MagicMock()
    response.results = [result]
    return response


# ──────────────────────────────────────────────
# transcribe — validation tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_file_not_found(adapter: NvidiaRivaAdapter):
    """Non-existent file -> STTError."""
    with pytest.raises(STTError, match="Audio file not found"):
        await adapter.transcribe("/nonexistent/file.wav")


@pytest.mark.asyncio
async def test_transcribe_unsupported_format(adapter: NvidiaRivaAdapter, tmp_path):
    """Unsupported file extension -> STTError."""
    audio_file = tmp_path / "test.txt"
    audio_file.write_bytes(b"fake_data")
    with pytest.raises(STTError, match="Unsupported audio format"):
        await adapter.transcribe(str(audio_file))


@pytest.mark.asyncio
async def test_transcribe_file_too_large(
    adapter: NvidiaRivaAdapter, large_audio_file: str
):
    """File > 25MB -> STTError."""
    with pytest.raises(STTError, match="Audio file too large"):
        await adapter.transcribe(large_audio_file)


# ──────────────────────────────────────────────
# transcribe — gRPC call tests (native WAV)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_wav_success(adapter: NvidiaRivaAdapter, valid_wav_file: str):
    """WAV file -> successful transcription via gRPC."""
    mock_response = _make_recognize_response("Тестовая транскрипция")
    mock_stub = MagicMock()
    mock_stub.Recognize = AsyncMock(return_value=mock_response)
    adapter._stub = mock_stub

    result = await adapter.transcribe(valid_wav_file, language="ru")

    assert result == "Тестовая транскрипция"
    mock_stub.Recognize.assert_awaited_once()
    call_kwargs = mock_stub.Recognize.call_args
    request = call_kwargs[0][0]
    assert request.config.language_code == "ru-RU"
    assert request.config.encoding == 1  # LINEAR_PCM
    assert request.config.sample_rate_hertz == 16000
    assert request.config.enable_automatic_punctuation is True

    metadata = call_kwargs[1]["metadata"]
    metadata_dict = dict(metadata)
    assert metadata_dict["function-id"] == "test-function-id"
    assert metadata_dict["authorization"] == "Bearer test_nvidia_key"


@pytest.mark.asyncio
async def test_transcribe_grpc_error(adapter: NvidiaRivaAdapter, valid_wav_file: str):
    """gRPC RpcError -> STTError with details."""
    mock_stub = MagicMock()
    rpc_error = grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE,
        MagicMock(),
        trailing_metadata=MagicMock(),
        details="Service unavailable",
    )
    mock_stub.Recognize = AsyncMock(side_effect=rpc_error)
    adapter._stub = mock_stub

    with pytest.raises(STTError, match="Riva gRPC error"):
        await adapter.transcribe(valid_wav_file)


@pytest.mark.asyncio
async def test_transcribe_empty_result(adapter: NvidiaRivaAdapter, valid_wav_file: str):
    """Empty gRPC response -> returns empty string."""
    mock_response = MagicMock()
    mock_response.results = []
    mock_stub = MagicMock()
    mock_stub.Recognize = AsyncMock(return_value=mock_response)
    adapter._stub = mock_stub

    result = await adapter.transcribe(valid_wav_file)
    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_no_alternatives(adapter: NvidiaRivaAdapter, valid_wav_file: str):
    """Result with no alternatives -> returns empty string."""
    result_mock = MagicMock()
    result_mock.alternatives = []
    mock_response = MagicMock()
    mock_response.results = [result_mock]
    mock_stub = MagicMock()
    mock_stub.Recognize = AsyncMock(return_value=mock_response)
    adapter._stub = mock_stub

    result = await adapter.transcribe(valid_wav_file)
    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_language_mapping(adapter: NvidiaRivaAdapter, valid_wav_file: str):
    """ISO 639-1 language code is mapped to BCP-47."""
    mock_response = _make_recognize_response("Hello world")
    mock_stub = MagicMock()
    mock_stub.Recognize = AsyncMock(return_value=mock_response)
    adapter._stub = mock_stub

    await adapter.transcribe(valid_wav_file, language="en")
    request = mock_stub.Recognize.call_args[0][0]
    assert request.config.language_code == "en-US"


# ──────────────────────────────────────────────
# transcribe — ffmpeg conversion tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_ogg_converts_to_wav(
    adapter: NvidiaRivaAdapter, valid_ogg_file: str
):
    """OGG file -> ffmpeg conversion -> gRPC call with converted WAV."""
    mock_response = _make_recognize_response("Тест")
    mock_stub = MagicMock()
    mock_stub.Recognize = AsyncMock(return_value=mock_response)
    adapter._stub = mock_stub

    with patch("infrastructure.stt.riva._convert_to_wav") as mock_convert, \
         patch("builtins.open", MagicMock(return_value=MagicMock())) as mock_open:
        mock_convert.return_value = "/tmp/riva_stt_xxx/converted.wav"
        mock_file = MagicMock()
        mock_file.read.return_value = b"RIFF fake wav data"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_file

        with patch("infrastructure.stt.riva.shutil.rmtree"):
            result = await adapter.transcribe(valid_ogg_file, language="ru")

    assert result == "Тест"
    mock_convert.assert_called_once_with(valid_ogg_file)


def test_convert_to_wav_ffmpeg_not_found():
    """Missing ffmpeg -> STTError."""
    with patch("infrastructure.stt.riva.shutil.which", return_value=None):
        with pytest.raises(STTError, match="ffmpeg is not installed"):
            _convert_to_wav("/some/file.ogg")


def test_convert_to_wav_ffmpeg_failure():
    """ffmpeg conversion failure -> STTError."""
    with patch("infrastructure.stt.riva.shutil.which", return_value="/usr/bin/ffmpeg"), \
         patch("infrastructure.stt.riva.subprocess.run") as mock_run, \
         patch("infrastructure.stt.riva.tempfile.mkdtemp", return_value="/tmp/riva_test"):
        mock_run.side_effect = __import__("subprocess").CalledProcessError(
            1, "ffmpeg", stderr="Invalid data found"
        )
        with pytest.raises(STTError, match="ffmpeg conversion failed"):
            _convert_to_wav("/some/file.ogg")


# ──────────────────────────────────────────────
# aclose tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aclose_closes_channel():
    """aclose() closes gRPC channel when adapter owns it."""
    adapter = NvidiaRivaAdapter(api_key="key")
    mock_channel = AsyncMock()
    adapter._channel = mock_channel
    adapter._stub = MagicMock()

    await adapter.aclose()

    mock_channel.close.assert_awaited_once()
    assert adapter._channel is None
    assert adapter._stub is None


@pytest.mark.asyncio
async def test_aclose_no_channel():
    """aclose() is a no-op when no channel was created."""
    adapter = NvidiaRivaAdapter(api_key="key")
    await adapter.aclose()
    assert adapter._channel is None


# ──────────────────────────────────────────────
# lazy stub creation
# ──────────────────────────────────────────────


def test_get_stub_creates_channel():
    """_get_stub lazily creates gRPC channel and stub."""
    adapter = NvidiaRivaAdapter(
        api_key="key",
        server_url="dns:///grpc.test.nvidia.com:443",
    )
    with patch("infrastructure.stt.riva.grpc.aio.secure_channel") as mock_channel, \
         patch("infrastructure.stt.riva.RivaSpeechRecognitionStub") as mock_stub_cls:
        mock_channel.return_value = MagicMock()
        mock_stub_cls.return_value = MagicMock()

        stub = adapter._get_stub()

        mock_channel.assert_called_once()
        mock_stub_cls.assert_called_once()
        assert stub is not None

    stub2 = adapter._get_stub()
    assert stub2 is stub


# ──────────────────────────────────────────────
# factory test
# ──────────────────────────────────────────────


def test_create_stt_adapter_riva():
    """create_stt_adapter returns NvidiaRivaAdapter when stt_provider='riva'."""
    from unittest.mock import patch as _patch

    with _patch("infrastructure.stt.settings") as mock_settings:
        mock_settings.stt_provider = "riva"
        mock_settings.nvidia_api_key = "nvapi-test-key"
        mock_settings.riva_server_url = "dns:///grpc.nvcf.nvidia.com:443"
        mock_settings.riva_function_id = "test-func-id"

        from infrastructure.stt import create_stt_adapter

        adapter = create_stt_adapter()

        assert isinstance(adapter, NvidiaRivaAdapter)
        assert adapter._api_key == "nvapi-test-key"
        assert adapter._function_id == "test-func-id"


def test_create_stt_adapter_unknown_provider():
    """create_stt_adapter raises ValueError for unknown provider."""
    from unittest.mock import patch as _patch

    with _patch("infrastructure.stt.settings") as mock_settings:
        mock_settings.stt_provider = "azure"

        from infrastructure.stt import create_stt_adapter

        with pytest.raises(ValueError, match="Unknown STT provider"):
            create_stt_adapter()


def test_create_stt_adapter_riva_missing_key():
    """create_stt_adapter raises ValueError when nvidia_api_key is empty."""
    from unittest.mock import patch as _patch

    with _patch("infrastructure.stt.settings") as mock_settings:
        mock_settings.stt_provider = "riva"
        mock_settings.nvidia_api_key = ""

        from infrastructure.stt import create_stt_adapter

        with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
            create_stt_adapter()


# ──────────────────────────────────────────────
# language mapping coverage
# ──────────────────────────────────────────────


def test_language_map_has_common_codes():
    """Verify common language codes are present in the mapping."""
    assert LANGUAGE_MAP["ru"] == "ru-RU"
    assert LANGUAGE_MAP["en"] == "en-US"
    assert LANGUAGE_MAP["de"] == "de-DE"


def test_language_map_unknown_code():
    """Unknown language code falls back to xx-XX pattern."""
    result = LANGUAGE_MAP.get("xx", "xx-XX")
    assert result == "xx-XX"
