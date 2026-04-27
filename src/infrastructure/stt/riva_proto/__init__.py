"""NVIDIA Riva ASR proto stubs for gRPC communication.

This package contains generated protobuf message classes and gRPC service stubs
sourced from nvidia-riva/common/riva/proto/.

Regeneration (if needed):
    python -m grpc_tools.protoc \\
        -I=<proto_root> \\
        --python_out=src/infrastructure/stt/riva_proto \\
        --grpc_python_out=src/infrastructure/stt/riva_proto \\
        riva/proto/riva_audio.proto \\
        riva/proto/riva_common.proto \\
        riva/proto/riva_asr.proto

After regeneration, fix imports in riva/proto/riva_asr_pb2.py and
riva/proto/riva_asr_pb2_grpc.py: change "from riva.proto import" to "from . import".
"""
