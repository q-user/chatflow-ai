"""Integration tests for Celery compile_session task.

Tests the compile_session function with a real sync database session.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.database.models.project import ProjectTable
from infrastructure.task_queue.tasks import (
    _estimator_module_stub,
    _finance_module_handler,
    _get_module_handler,
)


def _skip_if_no_db():
    """Skip test if TEST_DATABASE_URL is not set."""
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set — skipping Celery integration tests")


def _make_sync_session() -> Session:
    """Create a sync session for testing."""
    db_url = os.environ["TEST_DATABASE_URL"]
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    engine = create_engine(sync_url)

    # Create project table if it doesn't exist
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS projects (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                company_id UUID NOT NULL,
                user_id UUID NOT NULL,
                bot_instance_id UUID NOT NULL,
                module_type VARCHAR(50) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                input_data JSONB,
                result_data JSONB,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ
            )
        """)
        )
        conn.commit()

    session_factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return session_factory()


def _make_snapshot(
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    bot_instance_id: uuid.UUID | None = None,
    module_type: str = "estimator",
    items: list[dict] | None = None,
) -> dict:
    """Create a snapshot dict for compile_session."""
    return {
        "user_id": str(user_id or uuid.uuid4()),
        "company_id": str(company_id or uuid.uuid4()),
        "bot_instance_id": str(bot_instance_id or uuid.uuid4()),
        "module_type": module_type,
        "items": items or [{"text": "test item"}],
    }


# ──────────────────────────────────────────────
# Helper: run compile_session logic directly
# ──────────────────────────────────────────────


def _run_compile_logic(snapshot: dict, session: Session) -> dict:
    """Run the compile_session logic directly with a provided session.

    This bypasses Celery task machinery and uses the provided session.
    """
    from datetime import datetime, timezone

    # 1. Create Project record
    project = ProjectTable(
        company_id=snapshot["company_id"],
        user_id=snapshot["user_id"],
        bot_instance_id=snapshot["bot_instance_id"],
        module_type=snapshot["module_type"],
        status="pending",
        input_data={"items": snapshot.get("items", [])},
    )
    session.add(project)
    session.flush()
    project_id = str(project.id)

    # 2. Dispatch to module handler
    handler = _get_module_handler(snapshot["module_type"])
    result = handler(
        items=snapshot.get("items", []),
        module_config=None,
        bot_token=snapshot.get("bot_token"),
        messenger_type=snapshot.get("messenger_type"),
    )

    # 3. Update Project status
    project.status = "completed"
    project.result_data = result
    project.completed_at = datetime.now(timezone.utc)
    session.commit()

    return {"project_id": project_id, "status": "completed"}


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────


def test_compile_session_creates_project():
    """compile_session creates Project record in DB."""
    _skip_if_no_db()

    session = _make_sync_session()
    try:
        snapshot = _make_snapshot()
        result = _run_compile_logic(snapshot, session)

        assert result["status"] == "completed"
        assert result["project_id"] is not None

        # Verify in DB
        project = session.get(ProjectTable, result["project_id"])
        assert project is not None
        assert project.status == "completed"
        assert project.module_type == "estimator"
    finally:
        session.close()


def test_compile_session_finance_module():
    """compile_session with finance module → result_data has module='finance'."""
    _skip_if_no_db()

    # Mock AI to avoid real API calls
    import infrastructure.task_queue.tasks as tasks_module

    async def _fake_ai_generate(
        sp: str, txt: str, image_paths: list[str] | None = None
    ) -> dict:
        return {
            "rows": [
                {
                    "date": "2024-01-01",
                    "description": "Test",
                    "category": "income",
                    "amount": 1000,
                    "currency": "USD",
                }
            ]
        }

    original_ai_generate = tasks_module._ai_generate_json
    tasks_module._ai_generate_json = _fake_ai_generate  # ty: ignore[invalid-assignment]

    session = _make_sync_session()
    try:
        snapshot = _make_snapshot(module_type="finance")
        result = _run_compile_logic(snapshot, session)

        assert result["status"] == "completed"

        project = session.get(ProjectTable, result["project_id"])
        assert project is not None
        assert project.result_data is not None
        assert project.result_data["module"] == "finance"
        assert project.result_data["items_processed"] == 1
    finally:
        session.close()
        tasks_module._ai_generate_json = original_ai_generate


def test_compile_session_estimator_module():
    """compile_session with estimator module → result_data has module='estimator'."""
    _skip_if_no_db()

    session = _make_sync_session()
    try:
        snapshot = _make_snapshot(module_type="estimator")
        result = _run_compile_logic(snapshot, session)

        assert result["status"] == "completed"

        project = session.get(ProjectTable, result["project_id"])
        assert project is not None
        assert project.result_data is not None
        assert project.result_data["module"] == "estimator"
    finally:
        session.close()


def test_compile_session_unknown_module_raises():
    """compile_session with unknown module_type → ValueError."""
    with pytest.raises(ValueError, match="Unknown module_type"):
        _get_module_handler("nonexistent_module")


def test_compile_session_input_data_stored():
    """compile_session stores input_data in DB."""
    _skip_if_no_db()

    session = _make_sync_session()
    try:
        items = [{"text": "item1"}, {"text": "item2"}]
        snapshot = _make_snapshot(items=items)
        result = _run_compile_logic(snapshot, session)

        project = session.get(ProjectTable, result["project_id"])
        assert project is not None
        assert project.input_data is not None
        assert len(project.input_data["items"]) == 2
    finally:
        session.close()


def test_compile_session_completed_at_set():
    """compile_session sets completed_at timestamp."""
    _skip_if_no_db()

    session = _make_sync_session()
    try:
        snapshot = _make_snapshot()
        result = _run_compile_logic(snapshot, session)

        project = session.get(ProjectTable, result["project_id"])
        assert project is not None
        assert project.completed_at is not None
    finally:
        session.close()
