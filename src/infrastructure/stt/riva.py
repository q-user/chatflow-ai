"""NVIDIA Riva STT adapter — gRPC-based speech recognition."""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import grpc
from grpc.aio._channel import Channel as AioChannel

from core.interfaces.speech import ISpeechToText, STTError
from infrastructure.stt.riva_proto.riva.proto import (
    LINEAR_PCM,
    RecognitionConfig,
    RecognizeRequest,
    RivaSpeechRecognitionStub,
)

logger = logging.getLogger(__name__)

MAX_AUDIO_SIZE = 25 * 1024 * 1024

EXTENSIONS_NEEDING_CONVERT = {".ogg", ".mp3", ".m4a", ".webm"}
RIVA_NATIVE_EXTENSIONS = {".wav", ".opus", ".flac"}
SUPPORTED_EXTENSIONS = EXTENSIONS_NEEDING_CONVERT | RIVA_NATIVE_EXTENSIONS

LANGUAGE_MAP = {
    "ru": "ru-RU",
    "en": "en-US",
    "de": "de-DE",
    "es": "es-ES",
    "fr": "fr-FR",
    "zh": "zh-CN",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "pt": "pt-BR",
    "it": "it-IT",
    "nl": "nl-NL",
    "pl": "pl-PL",
    "tr": "tr-TR",
    "uk": "uk-UA",
}


def _convert_to_wav(src_path: str) -> str:
    """Convert audio file to 16kHz mono 16-bit PCM WAV via ffmpeg.

    Returns path to the converted WAV file in a temp directory.
    Caller is responsible for cleaning up the temp directory.
    """
    if shutil.which("ffmpeg") is None:
        raise STTError(
            "ffmpeg is not installed. Required for audio conversion to WAV format."
        )

    tmp_dir = tempfile.mkdtemp(prefix="riva_stt_")
    dst_path = str(Path(tmp_dir) / "converted.wav")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                src_path,
                "-f",
                "wav",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                dst_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise STTError(f"ffmpeg conversion failed: {e.stderr[:500]}") from e
    except FileNotFoundError as e:
        raise STTError(
            "ffmpeg is not installed. Required for audio conversion to WAV format."
        ) from e

    return dst_path


class NvidiaRivaAdapter(ISpeechToText):
    """NVIDIA Riva Cloud STT via gRPC.

    Uses the Recognize RPC for offline (batch) transcription.
    Audio files not in Riva-native formats (.wav, .opus, .flac) are
    automatically converted to 16kHz mono 16-bit PCM WAV via ffmpeg.
    """

    def __init__(
        self,
        api_key: str,
        server_url: str = "dns:///grpc.nvcf.nvidia.com:443",
        function_id: str = "b0e8b4a5-217c-40b7-9b96-17d84e666317",
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._server_url = server_url
        self._function_id = function_id
        self._timeout = timeout
        self._channel: AioChannel | None = None
        self._stub: RivaSpeechRecognitionStub | None = None

    def _get_stub(self) -> RivaSpeechRecognitionStub:
        """Lazily create gRPC channel and stub."""
        if self._stub is None:
            credentials = grpc.ssl_channel_credentials()
            self._channel = grpc.aio.secure_channel(self._server_url, credentials)
            self._stub = RivaSpeechRecognitionStub(self._channel)
        return self._stub

    async def transcribe(self, file_path: str, language: str = "ru") -> str:
        """Transcribe audio file via NVIDIA Riva gRPC Recognize.

        :param file_path: Local path to audio file.
        :param language: ISO 639-1 language code.
        :returns: Transcribed text.
        :raises STTError: On gRPC failure, conversion error, or invalid file.
        """
        path = Path(file_path)

        if not path.exists():
            raise STTError(f"Audio file not found: {file_path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise STTError(f"Unsupported audio format: {path.suffix}")
        size = path.stat().st_size
        if size > MAX_AUDIO_SIZE:
            raise STTError(f"Audio file too large: {size} bytes (max {MAX_AUDIO_SIZE})")

        wav_path: str | None = None
        result = ""
        try:
            if path.suffix.lower() in EXTENSIONS_NEEDING_CONVERT:
                wav_path = _convert_to_wav(str(path))
                audio_file = wav_path
            else:
                audio_file = str(path)

            language_code = LANGUAGE_MAP.get(language, f"{language}-{language.upper()}")

            with open(audio_file, "rb") as f:
                audio_bytes = f.read()

            request = RecognizeRequest(
                config=RecognitionConfig(
                    encoding=LINEAR_PCM,
                    sample_rate_hertz=16000,
                    language_code=language_code,
                    enable_automatic_punctuation=True,
                    max_alternatives=1,
                ),
                audio=audio_bytes,
            )

            metadata = [
                ("function-id", self._function_id),
                ("authorization", f"Bearer {self._api_key}"),
            ]

            result = await self._recognize(request, metadata)

        finally:
            if wav_path is not None:
                tmp_dir = str(Path(wav_path).parent)
                shutil.rmtree(tmp_dir, ignore_errors=True)

        return result

    async def _recognize(
        self, request: RecognizeRequest, metadata: list[tuple[str, str]]
    ) -> str:
        """Execute gRPC Recognize call and extract transcript."""
        stub = self._get_stub()
        try:
            response = await stub.Recognize(
                request,
                metadata=metadata,
                timeout=self._timeout,
            )
        except grpc.aio.AioRpcError as e:
            raise STTError(f"Riva gRPC error ({e.code()}): {e.details()}") from e

        if not response.results:
            return ""

        alternatives = response.results[0].alternatives
        if not alternatives:
            return ""

        return alternatives[0].transcript.strip()

    async def aclose(self) -> None:
        """Close the gRPC channel if we created it."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None
