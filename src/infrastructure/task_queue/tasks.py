"""Celery task for processing compiled session data.

Creates a Project record, dispatches to module-specific handler,
updates status, and delivers artifact to the user.
"""

import asyncio
import csv
import logging
import os
import uuid
from datetime import datetime, timezone

from infrastructure.database.models.project import ProjectTable
from infrastructure.database.session import _init_sync_engine, sync_session_factory
from infrastructure.messengers import create_adapter
from infrastructure.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)

# Fallback prompt for finance module when bot has no custom system_prompt
FINANCE_FALLBACK_PROMPT = (
    "<|think|>"
    "You are a financial data analyst. "
    "Extract structured financial data from the user text. "
    "Return a JSON object with a single key 'rows' containing an array of objects. "
    "Each object represents a financial entry with keys: "
    "'date', 'description', 'category', 'amount', 'currency'. "
    "If a field cannot be determined, use null. "
    "Respond ONLY with valid JSON."
)


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
    2. Dispatch to module handler based on module_type (with bot_config)
    3. Update Project (status=completed/failed)
    4. Deliver artifact to user via messenger adapter

    :param snapshot: Dict with keys:
        - user_id: UUID string
        - company_id: UUID string
        - bot_instance_id: UUID string
        - module_type: str
        - items: list of dicts with text/file metadata
        - bot_config: dict or None (optional system_prompt etc.)
        - bot_token: str (for delivery)
        - chat_id: str (for delivery)
        - messenger_type: str (for delivery)
    :returns: Dict with project_id and status.
    """
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

            # Get bot config for system_prompt etc.
            bot_config = snapshot.get("bot_config")

            result = handler(
                items=snapshot.get("items", []),
                module_config=bot_config,
                bot_token=snapshot.get("bot_token"),
                messenger_type=snapshot.get("messenger_type"),
            )

            # 3. Update Project status
            project.status = "completed"
            project.result_data = result
            project.completed_at = datetime.now(timezone.utc)
            session.commit()

        # 4. Deliver artifact to user (Ticket 3.5)
        artifact_path = result.get("artifact_path")
        if artifact_path and snapshot.get("chat_id") and snapshot.get("messenger_type"):
            _deliver_artifact(snapshot, artifact_path)

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
    """Get the processing handler for a module type."""
    handlers = {
        "finance": _finance_module_handler,
        "estimator": _estimator_module_stub,
        "hr": _hr_module_stub,
    }
    handler = handlers.get(module_type)
    if handler is None:
        raise ValueError(f"Unknown module_type: {module_type}")
    return handler


# ──────────────────────────────────────────────
# Module handlers
# ──────────────────────────────────────────────


def _finance_module_handler(
    items: list[dict],
    module_config: dict | None = None,
    bot_token: str | None = None,
    messenger_type: str | None = None,
) -> dict:
    """Finance module: AI-powered processing → CSV artifact.

    :param items: [{"text": ..., "file_id": ..., "file_type": ..., ...}]
    :param module_config: BotInstance.config dict (may contain "system_prompt")
    :param bot_token: Bot API token for file downloads.
    :param messenger_type: Messenger type for adapter creation.
    :returns: {"module": "finance", "artifact_path": str, "items_processed": int}
    :raises ValueError: If no text data or AI returned no rows.
    :raises AIServiceError: If AI call fails.
    """
    # 1. Concatenate text from items
    text_chunks = [item.get("text", "") for item in items if item.get("text")]
    if not text_chunks:
        raise ValueError("No text data in items for finance processing")
    combined_text = "\n---\n".join(text_chunks)

    # 2. System prompt: from config or fallback
    system_prompt = (module_config or {}).get(
        "system_prompt"
    ) or FINANCE_FALLBACK_PROMPT

    # 3. Filter image items
    file_items = [
        item
        for item in items
        if item.get("file_id") and item.get("file_type", "").startswith("image/")
    ]

    # 4. Single event loop: download images + call AI
    result_json = asyncio.run(
        _finance_ai_pipeline(
            system_prompt,
            combined_text,
            file_items,
            bot_token,
            messenger_type,
        )
    )

    # 5. Generate CSV from JSON
    csv_path = _write_csv(result_json)

    return {
        "module": "finance",
        "artifact_path": csv_path,
        "items_processed": len(items),
    }


def _estimator_module_stub(
    items: list[dict],
    module_config: dict | None = None,
    bot_token: str | None = None,
    messenger_type: str | None = None,
) -> dict:
    """Stub: estimator module handler."""
    return {
        "module": "estimator",
        "items_processed": len(items),
        "message": "Estimator module processing (stub)",
    }


def _hr_module_stub(
    items: list[dict],
    module_config: dict | None = None,
    bot_token: str | None = None,
    messenger_type: str | None = None,
) -> dict:
    """Stub: HR module handler."""
    return {
        "module": "hr",
        "items_processed": len(items),
        "message": "HR module processing (stub)",
    }


# ──────────────────────────────────────────────
# Finance helper functions
# ──────────────────────────────────────────────


async def _download_images(
    file_items: list[dict], bot_token: str, messenger_type: str
) -> list[str]:
    """Download image files from messenger via adapter.

    :param file_items: Items with file_id and file_type.
    :param bot_token: Bot API token.
    :param messenger_type: "TG", "YM", etc.
    :returns: List of local file paths.
    """
    adapter = create_adapter(messenger_type, bot_token)
    paths: list[str] = []
    try:
        for item in file_items:
            file_id = item["file_id"]
            ext = _mime_to_ext(item.get("file_type", "image/jpeg"))
            # TODO: cleanup downloaded images after AI processing (L1)
            dest = os.path.join("/tmp", f"img_{uuid.uuid4().hex[:8]}{ext}")
            try:
                path = await adapter.download_file(file_id, dest)
                paths.append(path)
            except Exception:
                logger.warning("Failed to download file %s, skipping", file_id)
    finally:
        await adapter.aclose()
    return paths


async def _finance_ai_pipeline(
    system_prompt: str,
    combined_text: str,
    file_items: list[dict],
    bot_token: str | None,
    messenger_type: str | None,
) -> dict:
    """Single async pipeline: download images + call AI.

    Uses one event loop instead of two separate asyncio.run() calls.
    """
    image_paths: list[str] | None = None
    if file_items and bot_token and messenger_type:
        image_paths = await _download_images(file_items, bot_token, messenger_type)
        # Normalize: [] → None (semantically clearer for text-only mode)
        image_paths = image_paths or None
    return await _ai_generate_json(
        system_prompt, combined_text, image_paths=image_paths
    )


def _mime_to_ext(mime: str) -> str:
    """Map MIME type to file extension for image files."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    return mapping.get(mime, ".jpg")


async def _ai_generate_json(
    system_prompt: str, text: str, image_paths: list[str] | None = None
) -> dict:
    """Async wrapper with proper resource cleanup."""
    from infrastructure.ai import create_ai_adapter

    ai = create_ai_adapter()
    try:
        return await ai.generate_json(
            system_prompt=system_prompt, text=text, image_paths=image_paths
        )
    finally:
        await ai.aclose()


def _write_csv(data: dict, output_dir: str = "/tmp") -> str:
    """Write AI JSON result to CSV file.

    :param data: {"rows": [{"date": ..., "description": ..., ...}]}
    :param output_dir: Directory for output file.
    :returns: Absolute path to the CSV file.
    :raises ValueError: If data has no 'rows' key or rows is empty.
    """
    rows = data.get("rows", [])
    if not rows:
        raise ValueError("AI returned no rows for CSV generation")

    # Determine columns from first row keys
    fieldnames = list(rows[0].keys())

    # Unique filename
    filename = f"finance_{uuid.uuid4().hex[:8]}.csv"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return filepath


# ──────────────────────────────────────────────
# Delivery
# ──────────────────────────────────────────────


def _deliver_artifact(snapshot: dict, artifact_path: str) -> None:
    """Send generated artifact back to user via messenger.

    :param snapshot: Session snapshot dict with chat_id, messenger_type, bot_token.
    :param artifact_path: Local path to the file to send.
    """
    bot_token = snapshot.get("bot_token")
    messenger_type = snapshot.get("messenger_type")
    chat_id = snapshot.get("chat_id")
    if not all([bot_token, messenger_type, chat_id]):
        logger.warning("Cannot deliver artifact: missing delivery fields in snapshot")
        return

    adapter = create_adapter(messenger_type, bot_token)

    async def _send() -> None:
        try:
            await adapter.send_file(
                chat_id=chat_id,
                file_path=artifact_path,
                caption="Результат обработки готов ✅",
            )
        finally:
            await adapter.aclose()

    asyncio.run(_send())
