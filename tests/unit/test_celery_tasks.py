"""Unit tests for Celery compile_session task stub handlers and Project domain."""

import uuid


from core.domain.project import Project
from infrastructure.task_queue.celery_app import celery_app


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
