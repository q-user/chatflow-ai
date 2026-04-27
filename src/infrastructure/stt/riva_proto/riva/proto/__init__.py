"""NVIDIA Riva ASR generated protobuf + gRPC stubs."""

from .riva_asr_pb2 import (
    RecognizeRequest,
    RecognizeResponse,
    RecognitionConfig,
    StreamingRecognitionConfig,
    StreamingRecognizeRequest,
    SpeechRecognitionResult,
    SpeechRecognitionAlternative,
)
from .riva_asr_pb2_grpc import RivaSpeechRecognitionStub
from .riva_audio_pb2 import AudioEncoding, LINEAR_PCM, FLAC, OGGOPUS, MULAW, ALAW
from .riva_common_pb2 import RequestId

__all__ = [
    "RecognizeRequest",
    "RecognizeResponse",
    "RecognitionConfig",
    "StreamingRecognitionConfig",
    "StreamingRecognizeRequest",
    "SpeechRecognitionResult",
    "SpeechRecognitionAlternative",
    "RivaSpeechRecognitionStub",
    "AudioEncoding",
    "LINEAR_PCM",
    "FLAC",
    "OGGOPUS",
    "MULAW",
    "ALAW",
    "RequestId",
]
