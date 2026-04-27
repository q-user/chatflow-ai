"""Port: speech-to-text interface."""

from abc import ABC, abstractmethod


class STTError(Exception):
    """Raised when STT service fails."""

    pass


class ISpeechToText(ABC):
    """Port: interface for speech-to-text providers.

    Implementations: GroqWhisperAdapter, NvidiaRivaAdapter.
    """

    @abstractmethod
    async def transcribe(self, file_path: str, language: str = "ru") -> str:
        """Transcribe audio file to text.

        :param file_path: Local path to audio file (.ogg, .mp3, .wav, .m4a).
        :param language: ISO 639-1 language code (default: "ru").
        :returns: Transcribed text (plain string).
        :raises STTError: On API failure, timeout, or unsupported format.
        """
        ...

    async def aclose(self) -> None:
        """Release underlying resources (HTTP connections, etc.).

        No-op by default. Override in adapters that manage their own clients.
        """
        pass  # default: no-op
