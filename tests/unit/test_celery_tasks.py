"""Unit tests for Celery compile_session task stub handlers and Project domain."""

import csv
import os
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from core.domain.project import Project
from infrastructure.task_queue.celery_app import celery_app
from infrastructure.task_queue.tasks import _write_csv, _write_report_csv


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


def test_compile_session_task_registered():
    """compile_session task is registered in Celery."""
    assert celery_app.tasks.get("compile_session") is not None


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


def test_compile_session_value_error_no_retry():
    """compile_session should propagate ValueError without manual retry."""
    from infrastructure.task_queue.tasks import compile_session

    mock_session = MagicMock()

    with (
        patch(
            "infrastructure.database.session.sync_session_factory",
            return_value=mock_session,
        ),
        patch("infrastructure.database.session._init_sync_engine"),
        patch(
            "infrastructure.task_queue.tasks._get_module_handler",
            side_effect=ValueError("Invalid data"),
        ),
    ):
        snapshot = {
            "company_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "bot_instance_id": str(uuid.uuid4()),
            "module_type": "finance",
        }

        with pytest.raises(ValueError, match="Invalid data"):
            compile_session(snapshot)


def test_init_sync_engine_raises_on_failure():
    """_init_sync_engine raises RuntimeError, not leaving sync_session_factory as None."""
    import infrastructure.database.session as session_mod

    original_engine = session_mod.sync_engine
    original_factory = session_mod.sync_session_factory

    try:
        session_mod.sync_engine = None
        session_mod.sync_session_factory = None

        with (
            patch.object(session_mod.settings, "database_sync_url", ""),
            patch.object(
                session_mod.settings, "database_url", "postgresql+asyncpg://u:p@h/d"
            ),
            patch(
                "infrastructure.database.session.create_engine",
                side_effect=ModuleNotFoundError("No module named 'psycopg2'"),
            ),
        ):
            with pytest.raises(
                RuntimeError, match="Failed to initialize sync DB engine"
            ):
                session_mod._init_sync_engine()

        assert session_mod.sync_session_factory is None
        assert session_mod.sync_engine is None
    finally:
        session_mod.sync_engine = original_engine
        session_mod.sync_session_factory = original_factory


def test_compile_session_raises_when_sync_engine_fails():
    """compile_session raises RuntimeError (not TypeError) when sync engine init fails."""
    from infrastructure.task_queue.tasks import compile_session

    with patch(
        "infrastructure.database.session._init_sync_engine",
        side_effect=RuntimeError(
            "Failed to initialize sync DB engine: No module named 'psycopg2'"
        ),
    ):
        snapshot = {
            "company_id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "bot_instance_id": uuid.uuid4(),
            "module_type": "finance",
        }

    with pytest.raises(RuntimeError, match="Failed to initialize sync DB engine"):
        compile_session(snapshot)


# ──────────────────────────────────────────────
# Task registration tests
# ──────────────────────────────────────────────


def test_process_stream_item_task_registered():
    assert celery_app.tasks.get("process_stream_item") is not None


def test_generate_report_task_registered():
    assert celery_app.tasks.get("generate_report") is not None


# ──────────────────────────────────────────────
# process_stream_item tests
# ──────────────────────────────────────────────


def test_process_stream_item_creates_project_and_delivers():
    from infrastructure.task_queue.tasks import process_stream_item

    mock_session = MagicMock()
    mock_project = MagicMock()
    mock_project.id = uuid.uuid4()
    mock_session.add = MagicMock()
    mock_session.flush = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_result = {
        "module": "finance",
        "artifact_path": "/tmp/fin.csv",
        "items_processed": 1,
    }

    with (
        patch(
            "infrastructure.database.session.sync_session_factory",
            return_value=mock_session,
        ),
        patch("infrastructure.database.session._init_sync_engine"),
        patch(
            "infrastructure.task_queue.tasks._finance_module_handler",
            return_value=mock_result,
        ),
        patch("infrastructure.task_queue.tasks._deliver_artifact") as mock_deliver,
    ):
        snapshot = {
            "company_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "bot_instance_id": str(uuid.uuid4()),
            "module_type": "finance",
            "items": [{"text": "Кофе 200 руб"}],
            "chat_id": "123",
            "messenger_type": "TG",
            "bot_token": "tok",
            "bot_config": None,
        }
        result = process_stream_item(snapshot)

    assert result["status"] == "completed"
    mock_deliver.assert_called_once()


def test_process_stream_item_failure_marks_project_failed():
    from infrastructure.task_queue.tasks import process_stream_item

    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.flush = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    fail_session = MagicMock()
    fail_project = MagicMock()
    fail_session.get = MagicMock(return_value=fail_project)
    fail_session.commit = MagicMock()
    fail_session.__enter__ = MagicMock(return_value=fail_session)
    fail_session.__exit__ = MagicMock(return_value=False)

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_session
        return fail_session

    with (
        patch(
            "infrastructure.database.session.sync_session_factory",
            side_effect=session_factory,
        ),
        patch("infrastructure.database.session._init_sync_engine"),
        patch(
            "infrastructure.task_queue.tasks._finance_module_handler",
            side_effect=ValueError("AI error"),
        ),
        patch("infrastructure.task_queue.tasks.sentry_sdk") as mock_sentry,
    ):
        snapshot = {
            "company_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "bot_instance_id": str(uuid.uuid4()),
            "module_type": "finance",
            "items": [{"text": "test"}],
        }

        with pytest.raises(ValueError, match="AI error"):
            process_stream_item(snapshot)

    mock_sentry.capture_exception.assert_called_once()
    fail_project.status = "failed"


def test_process_stream_item_sync_engine_not_initialized():
    from infrastructure.task_queue.tasks import process_stream_item

    with (
        patch("infrastructure.database.session._init_sync_engine"),
        patch("infrastructure.database.session.sync_session_factory", None),
    ):
        with pytest.raises(
            RuntimeError, match="sync_session_factory is not initialized"
        ):
            process_stream_item({"items": []})


# ──────────────────────────────────────────────
# generate_report tests
# ──────────────────────────────────────────────


def test_generate_report_with_rows(tmp_path):
    from infrastructure.task_queue.tasks import generate_report

    company_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    bot_id = str(uuid.uuid4())

    mock_proj = MagicMock()
    mock_proj.result_data = {
        "rows": [{"date": "2025-04-25", "amount": 100, "category": "food"}]
    }

    mock_session = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_proj]
    mock_session.scalars.return_value = mock_scalars
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "infrastructure.database.session.sync_session_factory",
            return_value=mock_session,
        ),
        patch("infrastructure.database.session._init_sync_engine"),
        patch("infrastructure.task_queue.tasks._write_report_csv") as mock_csv,
        patch("infrastructure.task_queue.tasks._deliver_artifact") as mock_deliver,
    ):
        mock_csv.return_value = "/tmp/report.csv"

        result = generate_report(
            user_id=user_id,
            company_id=company_id,
            bot_instance_id=bot_id,
            chat_id="123",
            messenger_type="TG",
            bot_token="tok",
            date_from="2025-04-25",
            date_to="2025-05-01",
            period_days=7,
        )

    assert result["rows_count"] == 1
    mock_deliver.assert_called_once()


def test_generate_report_no_rows_sends_text():
    from infrastructure.task_queue.tasks import generate_report

    company_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    bot_id = str(uuid.uuid4())

    mock_session = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_session.scalars.return_value = mock_scalars
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "infrastructure.database.session.sync_session_factory",
            return_value=mock_session,
        ),
        patch("infrastructure.database.session._init_sync_engine"),
        patch("infrastructure.task_queue.tasks._send_text_message") as mock_send,
    ):
        result = generate_report(
            user_id=user_id,
            company_id=company_id,
            bot_instance_id=bot_id,
            chat_id="123",
            messenger_type="TG",
            bot_token="tok",
            date_from="2025-04-01",
            date_to="2025-04-30",
            period_days=30,
        )

    assert result["rows_count"] == 0
    assert result["report_path"] is None
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args[1]
    assert "Нет данных" in call_kwargs["text"]


def test_generate_report_sync_engine_not_initialized():
    from infrastructure.task_queue.tasks import generate_report

    with (
        patch("infrastructure.database.session._init_sync_engine"),
        patch("infrastructure.database.session.sync_session_factory", None),
    ):
        with pytest.raises(
            RuntimeError, match="sync_session_factory is not initialized"
        ):
            generate_report(
                user_id=str(uuid.uuid4()),
                company_id=str(uuid.uuid4()),
                bot_instance_id=str(uuid.uuid4()),
                chat_id="123",
                messenger_type="TG",
                bot_token="tok",
                date_from="2025-04-01",
                date_to="2025-04-30",
            )


def test_generate_report_failure_sentry():
    from infrastructure.task_queue.tasks import generate_report

    mock_session = MagicMock()
    mock_session.scalars.side_effect = Exception("DB boom")
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "infrastructure.database.session.sync_session_factory",
            return_value=mock_session,
        ),
        patch("infrastructure.database.session._init_sync_engine"),
        patch("infrastructure.task_queue.tasks.sentry_sdk") as mock_sentry,
    ):
        with pytest.raises(Exception, match="DB boom"):
            generate_report(
                user_id=str(uuid.uuid4()),
                company_id=str(uuid.uuid4()),
                bot_instance_id=str(uuid.uuid4()),
                chat_id="123",
                messenger_type="TG",
                bot_token="tok",
                date_from="2025-04-01",
                date_to="2025-04-30",
            )

    mock_sentry.capture_exception.assert_called_once()


# ──────────────────────────────────────────────
# _write_report_csv tests
# ──────────────────────────────────────────────


def test_write_report_csv_creates_file(tmp_path):
    rows = [
        {"date": "2025-04-25", "description": "Coffee", "amount": 200},
        {"date": "2025-04-26", "description": "Taxi", "amount": 500},
    ]
    filepath = _write_report_csv(
        rows, "2025-04-01", "2025-04-30", output_dir=str(tmp_path)
    )

    assert os.path.exists(filepath)
    assert "report_2025-04-01_2025-04-30" in filepath

    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        read_rows = list(reader)

    assert len(read_rows) == 2
    assert read_rows[0]["description"] == "Coffee"


def test_write_report_csv_empty_rows_raises():
    with pytest.raises(ValueError, match="No rows to write"):
        _write_report_csv([], "2025-04-01", "2025-04-30")


# ──────────────────────────────────────────────
# _send_text_message tests
# ──────────────────────────────────────────────


def test_send_text_message_calls_adapter():
    from infrastructure.task_queue.tasks import _send_text_message

    mock_adapter = AsyncMock()
    mock_adapter.aclose = AsyncMock()

    with patch(
        "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
    ):
        _send_text_message("tok", "TG", "123", "Hello")

    mock_adapter.send_text.assert_awaited_once_with(chat_id="123", text="Hello")
    mock_adapter.aclose.assert_awaited_once()
