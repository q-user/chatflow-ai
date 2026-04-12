"""Unit tests for Celery compile_session task stub handlers and Project domain."""

import csv
import os
import uuid
from unittest.mock import AsyncMock, patch

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


def test_write_csv_empty_rows_raises():
    """_write_csv raises ValueError when rows is empty."""
    data = {"rows": []}
    with patch("infrastructure.task_queue.tasks.uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "abc123"
        try:
            _write_csv(data)
        except ValueError as e:
            assert "no rows" in str(e).lower()
        else:
            raise AssertionError("Expected ValueError")


def test_write_csv_no_rows_key_raises():
    """_write_csv raises ValueError when 'rows' key is missing."""
    data = {"other_key": "value"}
    with patch("infrastructure.task_queue.tasks.uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "abc123"
        try:
            _write_csv(data)
        except ValueError as e:
            assert "no rows" in str(e).lower()
        else:
            raise AssertionError("Expected ValueError")


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
# _mime_to_ext tests (Ticket 3.6)
# ──────────────────────────────────────────────


def test_mime_to_ext_known_types():
    """_mime_to_ext maps known image MIME types to extensions."""
    from infrastructure.task_queue.tasks import _mime_to_ext

    assert _mime_to_ext("image/jpeg") == ".jpg"
    assert _mime_to_ext("image/png") == ".png"
    assert _mime_to_ext("image/gif") == ".gif"
    assert _mime_to_ext("image/webp") == ".webp"


def test_mime_to_ext_unknown_type():
    """_mime_to_ext defaults to .jpg for unknown MIME types."""
    from infrastructure.task_queue.tasks import _mime_to_ext

    assert _mime_to_ext("application/pdf") == ".jpg"
    assert _mime_to_ext("image/svg") == ".jpg"  # not in mapping


# ──────────────────────────────────────────────
# _download_images tests (Ticket 3.6)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_images_success():
    """_download_images downloads files and returns paths."""
    from infrastructure.task_queue.tasks import _download_images

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(return_value="/tmp/file_abc123.jpg")
    mock_adapter.aclose = AsyncMock()

    file_items = [
        {"file_id": "file1", "file_type": "image/jpeg"},
        {"file_id": "file2", "file_type": "image/png"},
    ]

    with patch(
        "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
    ):
        paths = await _download_images(file_items, "test_token", "TG")

    assert len(paths) == 2
    assert mock_adapter.download_file.call_count == 2
    mock_adapter.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_images_skip_failed():
    """_download_images skips failed downloads and continues."""
    from infrastructure.task_queue.tasks import _download_images

    mock_adapter = AsyncMock()
    mock_adapter.download_file = AsyncMock(side_effect=Exception("Download failed"))
    mock_adapter.aclose = AsyncMock()

    file_items = [{"file_id": "file1", "file_type": "image/jpeg"}]

    with patch(
        "infrastructure.task_queue.tasks.create_adapter", return_value=mock_adapter
    ):
        paths = await _download_images(file_items, "test_token", "TG")

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
