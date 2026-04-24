"""Unit tests for Celery compile_session task stub handlers and Project domain."""

import csv
import os
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from core.domain.project import Project
from infrastructure.task_queue.celery_app import celery_app
from infrastructure.task_queue.tasks import _write_csv


# ──────────────────────────────────────────────
# Project domain model tests
# ──────────────────────────────────────────────


def test_project_default_status():
    """Project defaults to 'pending' status."""
    project = Project(
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_instance_id=uuid.uuid4(),
        module_type="finance",
    )
    assert project.status == "pending"
    assert project.input_data is None
    assert project.result_data is None
    assert project.error_message is None


def test_project_with_input_data():
    """Project can hold input snapshot data."""
    items = [{"text": "test", "file_id": None}]
    project = Project(
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_instance_id=uuid.uuid4(),
        module_type="finance",
        input_data={"items": items},
    )
    assert project.input_data is not None
    assert project.input_data["items"] == items


def test_project_with_result_data():
    """Project can store result data."""
    project = Project(
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_instance_id=uuid.uuid4(),
        module_type="finance",
        result_data={"output": "processed"},
    )
    assert project.result_data is not None
    assert project.result_data["output"] == "processed"


def test_project_completed_status():
    """Project can transition to completed status."""
    project = Project(
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_instance_id=uuid.uuid4(),
        module_type="finance",
        status="completed",
        result_data={"done": True},
    )
    assert project.status == "completed"


def test_project_failed_status():
    """Project can transition to failed status."""
    project = Project(
        company_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_instance_id=uuid.uuid4(),
        module_type="finance",
        status="failed",
        error_message="Something went wrong",
    )
    assert project.status == "failed"
    assert project.error_message is not None
    assert "went wrong" in project.error_message


# ──────────────────────────────────────────────
# Celery app configuration tests
# ──────────────────────────────────────────────


def test_celery_app_registered():
    """Celery app is properly configured."""
    assert celery_app is not None
    assert celery_app.main == "worker"


def test_dummy_task_registered():
    """Dummy task is registered for health checks."""
    assert celery_app.tasks.get("dummy_task") is not None


# ──────────────────────────────────────────────
# _write_csv tests
# ──────────────────────────────────────────────


def test_write_csv_creates_file(tmp_path):
    """_write_csv creates a valid CSV file from JSON data."""
    data = {
        "rows": [
            {"date": "2024-01-01", "amount": 100},
            {"date": "2024-01-02", "amount": 200},
        ]
    }
    filepath = _write_csv(data, output_dir=str(tmp_path))

    assert os.path.exists(filepath)
    assert filepath.endswith(".csv")

    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["date"] == "2024-01-01"
    assert rows[0]["amount"] == "100"


@pytest.mark.parametrize(
    "data",
    [
        {"rows": []},
        {"other_key": "value"},
    ],
)
def test_write_csv_missing_rows_raises(data):
    """_write_csv raises ValueError when rows is empty or missing."""
    with patch("infrastructure.task_queue.tasks.uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "abc123"
        with pytest.raises(ValueError, match="no rows"):
            _write_csv(data)


# ──────────────────────────────────────────────
# _deliver_artifact tests
# ──────────────────────────────────────────────


def test_deliver_artifact_calls_send_file():
    """_deliver_artifact creates adapter and calls send_file."""
    from infrastructure.task_queue.tasks import _deliver_artifact

    mock_adapter = AsyncMock()
    mock_adapter.aclose = AsyncMock()

    with patch(
        "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
    ):
        snapshot = {
            "bot_token": "test_token",
            "messenger_type": "TG",
            "chat_id": "123456",
        }
        _deliver_artifact(snapshot, "/tmp/test_file.csv")

    mock_adapter.send_file.assert_called_once_with(
        chat_id="123456",
        file_path="/tmp/test_file.csv",
        caption="Результат обработки готов ✅",
    )
    mock_adapter.aclose.assert_awaited_once()


def test_deliver_artifact_missing_fields():
    """_deliver_artifact skips delivery when required fields are missing."""
    from infrastructure.task_queue.tasks import _deliver_artifact

    with patch("infrastructure.task_queue.tasks.create_adapter") as mock_create:
        # Missing bot_token
        snapshot = {"messenger_type": "TG", "chat_id": "123"}
        _deliver_artifact(snapshot, "/tmp/file.csv")
        mock_create.assert_not_called()

        # Missing messenger_type
        snapshot = {"bot_token": "token", "chat_id": "123"}
        _deliver_artifact(snapshot, "/tmp/file.csv")
        mock_create.assert_not_called()

        # Missing chat_id
        snapshot = {"bot_token": "token", "messenger_type": "TG"}
        _deliver_artifact(snapshot, "/tmp/file.csv")
        mock_create.assert_not_called()


# ──────────────────────────────────────────────
# _get_file_info tests (Merged from mime_to_ext and classify_file)
# ──────────────────────────────────────────────


def test_get_file_info_known_types():
    """_get_file_info maps known MIME types to extensions and categories."""
    from infrastructure.task_queue.tasks import _get_file_info

    # Images
    assert _get_file_info("image/jpeg") == ("image", ".jpg")
    assert _get_file_info("image/png") == ("image", ".png")
    assert _get_file_info("image/gif") == ("image", ".gif")
    assert _get_file_info("image/webp") == ("image", ".webp")
    # Audio
    assert _get_file_info("audio/ogg") == ("audio", ".ogg")
    assert _get_file_info("audio/mpeg") == ("audio", ".mp3")
    assert _get_file_info("audio/wav") == ("audio", ".wav")
    # Documents
    assert _get_file_info("application/pdf") == ("document", ".pdf")


def test_get_file_info_unknown_type():
    """_get_file_info defaults to (.bin, 'unknown') for unknown MIME types."""
    from infrastructure.task_queue.tasks import _get_file_info

    assert _get_file_info("unknown/type") == ("unknown", ".bin")
    assert _get_file_info("text/plain") == ("unknown", ".bin")


# ──────────────────────────────────────────────
# _download_and_parse_media tests (Ticket 4.3)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_and_parse_media_images_only():
    """_download_and_parse_media with only images returns empty text + image paths."""
    from infrastructure.task_queue.tasks import _download_and_parse_media

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(return_value="/tmp/img_abc123.jpg")
    mock_adapter.aclose = AsyncMock()

    file_items = [
        {"file_id": "file1", "file_type": "image/jpeg"},
        {"file_id": "file2", "file_type": "image/png"},
    ]

    with (
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
    ):
        text, paths = await _download_and_parse_media(file_items, "test_token", "TG")

    assert text == ""
    assert len(paths) == 2
    mock_adapter.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_and_parse_media_audio():
    """_download_and_parse_media transcribes audio files."""
    from infrastructure.task_queue.tasks import _download_and_parse_media

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(return_value="/tmp/audio_abc123.ogg")
    mock_adapter.aclose = AsyncMock()

    mock_stt = AsyncMock()
    mock_stt.transcribe = AsyncMock(return_value="Привет мир")
    mock_stt.aclose = AsyncMock()

    file_items = [{"file_id": "file1", "file_type": "audio/ogg"}]

    with (
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
        patch("infrastructure.stt.create_stt_adapter", return_value=mock_stt),
    ):
        text, paths = await _download_and_parse_media(file_items, "test_token", "TG")

    assert "[Транскрипция аудио]:" in text
    assert "Привет мир" in text
    assert paths == []
    mock_adapter.aclose.assert_awaited_once()
    mock_stt.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_and_parse_media_document():
    """_download_and_parse_media parses documents."""
    from infrastructure.task_queue.tasks import _download_and_parse_media

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(return_value="/tmp/doc_abc123.pdf")
    mock_adapter.aclose = AsyncMock()

    mock_stt = AsyncMock()
    mock_stt.aclose = AsyncMock()

    file_items = [{"file_id": "file1", "file_type": "application/pdf"}]

    with (
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
        patch("infrastructure.stt.create_stt_adapter", return_value=mock_stt),
        patch(
            "infrastructure.parsers.process_document",
            return_value="Document content here",
        ),
    ):
        text, paths = await _download_and_parse_media(file_items, "test_token", "TG")

    assert "[Содержимое документа]:" in text
    assert "Document content here" in text
    assert paths == []


@pytest.mark.asyncio
async def test_download_and_parse_media_skip_failed():
    """_download_and_parse_media skips failed downloads."""
    from infrastructure.task_queue.tasks import _download_and_parse_media

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(side_effect=Exception("fail"))
    mock_adapter.aclose = AsyncMock()

    file_items = [{"file_id": "bad", "file_type": "image/jpeg"}]

    with (
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
    ):
        text, paths = await _download_and_parse_media(file_items, "test_token", "TG")

    assert text == ""
    assert paths == []
    mock_adapter.aclose.assert_awaited_once()


# ──────────────────────────────────────────────
# _ai_generate_json with image_paths (Ticket 3.6)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_generate_json_with_images():
    """_ai_generate_json passes image_paths to AI adapter."""
    from infrastructure.task_queue.tasks import _ai_generate_json

    mock_ai = AsyncMock()
    mock_ai.generate_json = AsyncMock(return_value={"rows": [{"a": 1}]})
    mock_ai.aclose = AsyncMock()

    with patch("infrastructure.ai.create_ai_adapter", return_value=mock_ai):
        result = await _ai_generate_json(
            "prompt", "text", image_paths=["/tmp/img1.jpg", "/tmp/img2.png"]
        )

    assert result == {"rows": [{"a": 1}]}
    mock_ai.generate_json.assert_awaited_once_with(
        system_prompt="prompt",
        text="text",
        image_paths=["/tmp/img1.jpg", "/tmp/img2.png"],
    )
    mock_ai.aclose.assert_awaited_once()


# ──────────────────────────────────────────────
# _finance_ai_pipeline tests (Ticket 3.6 — vision flow)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finance_ai_pipeline_with_images():
    """_finance_ai_pipeline downloads images and passes them to AI."""
    from infrastructure.task_queue.tasks import _finance_ai_pipeline

    mock_ai = AsyncMock()
    mock_ai.generate_json = AsyncMock(return_value={"rows": [{"a": 1}]})
    mock_ai.aclose = AsyncMock()

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(return_value="/tmp/img_abc123.jpg")
    mock_adapter.aclose = AsyncMock()

    file_items = [{"file_id": "receipt_1", "file_type": "image/jpeg"}]

    with (
        patch("infrastructure.ai.create_ai_adapter", return_value=mock_ai),
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
    ):
        result = await _finance_ai_pipeline(
            "prompt", "text", file_items, "test_token", "TG"
        )

    assert result == {"rows": [{"a": 1}]}
    mock_ai.generate_json.assert_awaited_once()
    call_kwargs = mock_ai.generate_json.call_args[1]
    assert call_kwargs["image_paths"] == ["/tmp/img_abc123.jpg"]
    mock_ai.aclose.assert_awaited_once()
    mock_adapter.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_finance_ai_pipeline_text_only():
    """_finance_ai_pipeline without images — no download, AI gets image_paths=None."""
    from infrastructure.task_queue.tasks import _finance_ai_pipeline

    mock_ai = AsyncMock()
    mock_ai.generate_json = AsyncMock(return_value={"rows": []})
    mock_ai.aclose = AsyncMock()

    with patch("infrastructure.ai.create_ai_adapter", return_value=mock_ai):
        result = await _finance_ai_pipeline(
            "prompt", "text", file_items=[], bot_token=None, messenger_type=None
        )

    assert result == {"rows": []}
    call_kwargs = mock_ai.generate_json.call_args[1]
    assert call_kwargs["image_paths"] is None
    mock_ai.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_finance_ai_pipeline_all_images_fail():
    """_finance_ai_pipeline normalizes [] → None when all downloads fail."""
    from infrastructure.task_queue.tasks import _finance_ai_pipeline

    mock_ai = AsyncMock()
    mock_ai.generate_json = AsyncMock(return_value={"rows": []})
    mock_ai.aclose = AsyncMock()

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(side_effect=Exception("fail"))
    mock_adapter.aclose = AsyncMock()

    file_items = [{"file_id": "bad", "file_type": "image/jpeg"}]

    with (
        patch("infrastructure.ai.create_ai_adapter", return_value=mock_ai),
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
    ):
        result = await _finance_ai_pipeline(
            "prompt", "text", file_items, "test_token", "TG"
        )

    assert result == {"rows": []}
    call_kwargs = mock_ai.generate_json.call_args[1]
    # [] → None normalization
    assert call_kwargs["image_paths"] is None


@pytest.mark.asyncio
async def test_finance_ai_pipeline_with_audio():
    """_finance_ai_pipeline transcribes audio and merges with text."""
    from infrastructure.task_queue.tasks import _finance_ai_pipeline

    mock_ai = AsyncMock()
    mock_ai.generate_json = AsyncMock(return_value={"rows": [{"a": 1}]})
    mock_ai.aclose = AsyncMock()

    mock_stt = AsyncMock()
    mock_stt.transcribe = AsyncMock(return_value="Audio transcription text")
    mock_stt.aclose = AsyncMock()

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(return_value="/tmp/audio.ogg")
    mock_adapter.aclose = AsyncMock()

    file_items = [{"file_id": "audio_1", "file_type": "audio/ogg"}]

    with (
        patch("infrastructure.ai.create_ai_adapter", return_value=mock_ai),
        patch("infrastructure.stt.create_stt_adapter", return_value=mock_stt),
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
    ):
        result = await _finance_ai_pipeline(
            "prompt", "User message", file_items, "test_token", "TG"
        )

    assert result == {"rows": [{"a": 1}]}
    mock_stt.transcribe.assert_awaited_once_with("/tmp/audio.ogg")
    call_kwargs = mock_ai.generate_json.call_args[1]
    assert "Транскрипция аудио" in call_kwargs["text"]
    mock_ai.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_finance_ai_pipeline_with_document():
    """_finance_ai_pipeline extracts text from document and merges with text."""
    from infrastructure.task_queue.tasks import _finance_ai_pipeline

    mock_ai = AsyncMock()
    mock_ai.generate_json = AsyncMock(return_value={"rows": [{"a": 1}]})
    mock_ai.aclose = AsyncMock()

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(return_value="/tmp/doc.pdf")
    mock_adapter.aclose = AsyncMock()

    file_items = [{"file_id": "doc_1", "file_type": "application/pdf"}]

    with (
        patch("infrastructure.ai.create_ai_adapter", return_value=mock_ai),
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
        patch(
            "infrastructure.parsers.process_document", return_value="Extracted doc text"
        ),
    ):
        result = await _finance_ai_pipeline(
            "prompt", "User message", file_items, "test_token", "TG"
        )

    assert result == {"rows": [{"a": 1}]}
    call_kwargs = mock_ai.generate_json.call_args[1]
    assert "Содержимое документа" in call_kwargs["text"]
    mock_ai.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_finance_ai_pipeline_with_audio_and_document():
    """_finance_ai_pipeline merges audio transcription + document text."""
    from infrastructure.task_queue.tasks import _finance_ai_pipeline

    mock_ai = AsyncMock()
    mock_ai.generate_json = AsyncMock(return_value={"rows": [{"a": 1}]})
    mock_ai.aclose = AsyncMock()

    mock_stt = AsyncMock()
    mock_stt.transcribe = AsyncMock(return_value="Spoken words")
    mock_stt.aclose = AsyncMock()

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(side_effect=lambda fid, dest: dest)
    mock_adapter.aclose = AsyncMock()

    file_items = [
        {"file_id": "audio_1", "file_type": "audio/ogg"},
        {"file_id": "doc_1", "file_type": "application/pdf"},
    ]

    with (
        patch("infrastructure.ai.create_ai_adapter", return_value=mock_ai),
        patch("infrastructure.stt.create_stt_adapter", return_value=mock_stt),
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
        patch("infrastructure.parsers.process_document", return_value="Doc text"),
    ):
        result = await _finance_ai_pipeline(
            "prompt", "User message", file_items, "test_token", "TG"
        )

    assert result == {"rows": [{"a": 1}]}
    call_kwargs = mock_ai.generate_json.call_args[1]
    assert "Транскрипция аудио" in call_kwargs["text"]
    assert "Содержимое документа" in call_kwargs["text"]


def test_deliver_artifact_cleanup_once():
    """_deliver_artifact deletes the artifact exactly once."""
    from infrastructure.task_queue.tasks import _deliver_artifact

    mock_adapter = AsyncMock()
    mock_adapter.aclose = AsyncMock()

    with (
        patch(
            "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
        ),
        patch("infrastructure.task_queue.tasks.os.unlink") as mock_unlink,
    ):
        snapshot = {
            "bot_token": "test_token",
            "messenger_type": "TG",
            "chat_id": "123456",
        }
        _deliver_artifact(snapshot, "/tmp/test_file.csv")

    mock_unlink.assert_called_once_with("/tmp/test_file.csv")


@pytest.mark.asyncio
async def test_compile_session_value_error_no_retry():
    """compile_session should propagate ValueError without manual retry."""
    from infrastructure.task_queue.tasks import compile_session

    with patch(
        "infrastructure.task_queue.tasks._get_module_handler"
    ) as mock_get_handler:
        mock_handler = MagicMock()
        mock_handler.side_effect = ValueError("Invalid data")
        mock_get_handler.return_value = mock_handler

        with (
            patch("infrastructure.task_queue.tasks.sync_session_factory"),
            patch("infrastructure.task_queue.tasks._init_sync_engine"),
        ):
            snapshot = {
                "company_id": uuid.uuid4(),
                "user_id": uuid.uuid4(),
                "bot_instance_id": uuid.uuid4(),
                "module_type": "finance",
            }

            with pytest.raises(ValueError, match="Invalid data"):
                compile_session(snapshot)
