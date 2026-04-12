"""Celery task for processing compiled session data.

Creates a Project record, dispatches to module-specific handler,
updates status, and notifies the user.
"""

import logging
from datetime import datetime, timezone

from infrastructure.database.models.project import ProjectTable
from infrastructure.database.session import _init_sync_engine, sync_session_factory
from infrastructure.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="compile_session",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def compile_session(self, snapshot: dict) -> dict:
    """Process accumulated session data.

    Pipeline:
    1. Create Project record (status=pending)
    2. Dispatch to module handler based on module_type
    3. Update Project (status=completed/failed)
    4. Notify user via messenger adapter (TODO)

    :param snapshot: Dict with keys:
        - user_id: UUID string
        - company_id: UUID string
        - bot_instance_id: UUID string
        - module_type: str
        - items: list of dicts with text/file metadata
    :returns: Dict with project_id and status.
    """
    import uuid

    # Lazy init — only when task actually runs (not at import time)
    _init_sync_engine()

    project_id = None
    try:
        # Use sync session for Celery task
        with sync_session_factory() as session:
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
            result = handler(snapshot.get("items", []))

            # 3. Update Project status
            project.status = "completed"
            project.result_data = result
            project.completed_at = datetime.now(timezone.utc)
            session.commit()

        return {"project_id": project_id, "status": "completed"}

    except Exception as exc:
        # Update project to failed
        if project_id:
            try:
                with sync_session_factory() as session:
                    project = session.get(ProjectTable, uuid.UUID(project_id))
                    if project:
                        project.status = "failed"
                        project.error_message = str(exc)
                        session.commit()
            except Exception:
                logger.exception("Failed to update project status for %s", project_id)

        logger.exception("compile_session failed for project %s", project_id)
        raise self.retry(exc=exc) from exc


def _get_module_handler(module_type: str):
    """Get the processing handler for a module type.

    Currently returns stub handlers — full implementation in Step 3.
    """
    handlers = {
        "finance": _finance_module_stub,
        "estimator": _estimator_module_stub,
        "hr": _hr_module_stub,
    }
    handler = handlers.get(module_type)
    if handler is None:
        raise ValueError(f"Unknown module_type: {module_type}")
    return handler


# ──────────────────────────────────────────────
# Stub module handlers (full logic in Step 3)
# ──────────────────────────────────────────────


def _finance_module_stub(items: list[dict]) -> dict:
    """Stub: finance module handler."""
    return {
        "module": "finance",
        "items_processed": len(items),
        "message": "Finance module processing (stub)",
    }


def _estimator_module_stub(items: list[dict]) -> dict:
    """Stub: estimator module handler."""
    return {
        "module": "estimator",
        "items_processed": len(items),
        "message": "Estimator module processing (stub)",
    }


def _hr_module_stub(items: list[dict]) -> dict:
    """Stub: HR module handler."""
    return {
        "module": "hr",
        "items_processed": len(items),
        "message": "HR module processing (stub)",
    }
