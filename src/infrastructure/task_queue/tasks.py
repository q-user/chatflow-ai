"""Celery task for processing compiled session data.

Creates a Project record, dispatches to module-specific handler,
updates status, and delivers artifact to the user.
"""

import asyncio
import csv
import logging
import os
import uuid
import httpx
from kombu.exceptions import OperationalError
from datetime import datetime, timedelta, timezone
from typing import Any

import sentry_sdk
from infrastructure.database.models.project import ProjectTable
from infrastructure.database import session as db_session
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

FILE_CATEGORY_PREFIXES = {
    "image": "img",
    "audio": "audio",
    "document": "doc",
    "unknown": "file",
}


@celery_app.task(
    name="compile_session",
    bind=True,
    autoretry_for=(httpx.RequestError, OperationalError),
    retry_backoff=30,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=900,
    time_limit=960,
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
    db_session._init_sync_engine()

    if db_session.sync_session_factory is None:
        raise RuntimeError(
            "sync_session_factory is not initialized. "
            "Ensure psycopg2-binary is installed and DATABASE_SYNC_URL is set correctly."
        )

    project_id = None
    try:
        # Use sync session for Celery task
        with db_session.sync_session_factory() as session:
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
                with db_session.sync_session_factory() as session:
                    project = session.get(ProjectTable, uuid.UUID(project_id))
                    if project:
                        project.status = "failed"
                        project.error_message = str(exc)
                        session.commit()
            except Exception:
                logger.exception("Failed to update project status for %s", project_id)

        sentry_sdk.capture_exception(exc)
        logger.exception("compile_session failed for project %s", project_id)
        raise


@celery_app.task(
    name="process_stream_item",
    bind=True,
    autoretry_for=(httpx.RequestError, OperationalError),
    retry_backoff=30,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=900,
    time_limit=960,
)
def process_stream_item(self, snapshot: dict) -> dict:
    """Process a single finance-stream item (text or file).

    Creates a Project record, runs the finance module handler,
    updates status, and delivers CSV artifact to the user.

    :param snapshot: SessionSnapshot dict with single item in items list.
    :returns: Dict with project_id and status.
    """
    db_session._init_sync_engine()

    if db_session.sync_session_factory is None:
        raise RuntimeError(
            "sync_session_factory is not initialized. "
            "Ensure psycopg2-binary is installed and DATABASE_SYNC_URL is set correctly."
        )

    project_id = None
    try:
        with db_session.sync_session_factory() as session:
            project = ProjectTable(
                company_id=snapshot["company_id"],
                user_id=snapshot["user_id"],
                bot_instance_id=snapshot["bot_instance_id"],
                module_type=snapshot.get("module_type", "finance"),
                status="pending",
                input_data={"items": snapshot.get("items", [])},
            )
            session.add(project)
            session.flush()
            project_id = str(project.id)

            handler = _finance_module_handler
            bot_config = snapshot.get("bot_config")
            result = handler(
                items=snapshot.get("items", []),
                module_config=bot_config,
                bot_token=snapshot.get("bot_token"),
                messenger_type=snapshot.get("messenger_type"),
            )

            project.status = "completed"
            project.result_data = result
            project.completed_at = datetime.now(timezone.utc)
            session.commit()

            artifact_path = result.get("artifact_path")
            if (
                artifact_path
                and snapshot.get("chat_id")
                and snapshot.get("messenger_type")
            ):
                _deliver_artifact(snapshot, artifact_path)

            return {"project_id": project_id, "status": "completed"}

    except Exception as exc:
        if project_id:
            try:
                with db_session.sync_session_factory() as session:
                    project = session.get(ProjectTable, uuid.UUID(project_id))
                    if project:
                        project.status = "failed"
                        project.error_message = str(exc)
                        session.commit()
            except Exception:
                logger.exception("Failed to update project status for %s", project_id)

        sentry_sdk.capture_exception(exc)
        logger.exception("process_stream_item failed for project %s", project_id)
        raise


@celery_app.task(
    name="generate_report",
    bind=True,
    autoretry_for=(httpx.RequestError, OperationalError),
    retry_backoff=30,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=300,
    time_limit=360,
)
def generate_report(
    self,
    user_id: str,
    company_id: str,
    bot_instance_id: str,
    chat_id: str,
    messenger_type: str,
    bot_token: str,
    date_from: str,
    date_to: str,
    period_days: int = 7,
) -> dict:
    """Generate a CSV report from finance projects in the given date range.

    Queries completed finance projects for the user/company, extracts
    all rows from result_data, writes a combined CSV, and delivers it.

    :param user_id: UUID string of the user.
    :param company_id: UUID string of the company.
    :param bot_instance_id: UUID string of the bot instance.
    :param chat_id: Chat ID to deliver the report to.
    :param messenger_type: Messenger type for delivery.
    :param bot_token: Bot token for delivery.
    :param date_from: ISO date string YYYY-MM-DD (inclusive).
    :param date_to: ISO date string YYYY-MM-DD (inclusive).
    :param period_days: Number of days in the period (for metadata).
    :returns: Dict with report_path and rows_count.
    """
    db_session._init_sync_engine()

    if db_session.sync_session_factory is None:
        raise RuntimeError(
            "sync_session_factory is not initialized. "
            "Ensure psycopg2-binary is installed and DATABASE_SYNC_URL is set correctly."
        )

    try:
        from sqlalchemy import select

        with db_session.sync_session_factory() as session:
            start = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(date_to).replace(
                tzinfo=timezone.utc
            ) + timedelta(days=1)

            stmt = (
                select(ProjectTable)
                .where(
                    ProjectTable.company_id == uuid.UUID(company_id),
                    ProjectTable.user_id == uuid.UUID(user_id),
                    ProjectTable.bot_instance_id == uuid.UUID(bot_instance_id),
                    ProjectTable.module_type == "finance",
                    ProjectTable.status == "completed",
                    ProjectTable.completed_at >= start,
                    ProjectTable.completed_at < end,
                )
                .order_by(ProjectTable.completed_at)
            )
            projects: list[Any] = list(session.scalars(stmt).all())

        all_rows: list[dict] = []
        for proj in projects:
            if proj.result_data and "rows" in (proj.result_data or {}):
                all_rows.extend(proj.result_data["rows"])

        if not all_rows:
            _send_text_message(
                bot_token=bot_token,
                messenger_type=messenger_type,
                chat_id=chat_id,
                text=(
                    f"Нет данных за период {date_from} — {date_to}. "
                    "Отправьте расход или чек, а затем запросите отчёт: /report"
                ),
            )
            return {"report_path": None, "rows_count": 0}

        csv_path = _write_report_csv(all_rows, date_from, date_to)

        snapshot = {
            "bot_token": bot_token,
            "messenger_type": messenger_type,
            "chat_id": chat_id,
        }
        _deliver_artifact(snapshot, csv_path)

        return {"report_path": csv_path, "rows_count": len(all_rows)}

    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.exception("generate_report failed for user %s", user_id)
        raise


def _write_report_csv(
    rows: list[dict], date_from: str, date_to: str, output_dir: str = "/tmp"
) -> str:
    """Write combined report rows to CSV.

    :param rows: List of row dicts from finance projects.
    :param date_from: ISO date for filename.
    :param date_to: ISO date for filename.
    :param output_dir: Output directory.
    :returns: Absolute path to the CSV file.
    """
    if not rows:
        raise ValueError("No rows to write for report CSV")

    fieldnames = list(rows[0].keys())
    filename = f"report_{date_from}_{date_to}_{uuid.uuid4().hex[:8]}.csv"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return filepath


def _send_text_message(
    bot_token: str, messenger_type: str, chat_id: str, text: str
) -> None:
    """Send a plain text message via messenger adapter (sync wrapper)."""
    adapter = create_adapter(messenger_type, bot_token)

    async def _send() -> None:
        try:
            await adapter.send_text(chat_id=chat_id, text=text)
        finally:
            await adapter.aclose()

    asyncio.run(_send())


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
    text_chunks = [item.get("text", "") for item in items if item.get("text")]
    combined_text = "\n---\n".join(text_chunks)

    logger.info(
        "Finance handler: %d items, %d text_chunks, %d file_items. Items: %s",
        len(items),
        len(text_chunks),
        sum(1 for i in items if i.get("file_id") and i.get("file_type")),
        items,
    )

    # 2. System prompt: from config or fallback (with today's date injected)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system_prompt = (module_config or {}).get(
        "system_prompt"
    ) or FINANCE_FALLBACK_PROMPT
    system_prompt += (
        f"\nToday's date: {today}. If the user does not specify a date, use today."
    )

    # 3. Filter ALL file items (not just images)
    file_items = [
        item for item in items if item.get("file_id") and item.get("file_type")
    ]

    # 4. Single event loop: download + parse media + call AI
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
        "rows": result_json.get("rows", []),
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


async def _download_and_parse_media(
    file_items: list[dict],
    bot_token: str,
    messenger_type: str,
) -> tuple[str, list[str]]:
    """Download all files, parse audio/docs to text, collect image paths.

    Single async pipeline — one messenger adapter, one STT adapter,
    proper resource cleanup via finally blocks.

    :param file_items: Items with file_id and file_type.
    :param bot_token: Bot API token.
    :param messenger_type: "TG", "YM", etc.
    :returns: Tuple of (parsed_text, image_paths).
        parsed_text: Concatenated text from audio transcriptions + document parsing.
        image_paths: Local paths to downloaded image files for Vision.
    """
    from infrastructure.parsers import process_document
    # lazy STT init

    adapter = create_adapter(messenger_type, bot_token)
    stt = None
    parsed_parts: list[str] = []
    image_paths: list[str] = []

    try:
        for item in file_items:
            file_id = item["file_id"]
            file_type = item.get("file_type")
            category, ext = _get_file_info(file_type)
            dest = os.path.join(
                "/tmp",
                f"{FILE_CATEGORY_PREFIXES[category]}_{uuid.uuid4().hex[:8]}{ext}",
            )
            logger.info(
                "Processing file: id=%s, mime=%s, category=%s, dest=%s",
                file_id,
                file_type,
                category,
                dest,
            )

            # Download
            try:
                local_path = await adapter.download_file(file_id, dest)
                file_size = (
                    os.path.getsize(local_path) if os.path.exists(local_path) else 0
                )
                logger.info(
                    "Downloaded file: path=%s, size=%d bytes", local_path, file_size
                )
            except Exception:
                logger.warning(
                    "Failed to download file %s, skipping", file_id, exc_info=True
                )
                continue

            # Route by category
            try:
                if category == "image":
                    image_paths.append(local_path)
                    logger.info("Added image: %s", local_path)
                elif category == "audio":
                    if stt is None:
                        from infrastructure.stt import create_stt_adapter

                        stt = create_stt_adapter()
                        logger.info(
                            "Initialized STT adapter: provider=%s",
                            create_stt_adapter.__module__,
                        )
                    try:
                        text = await stt.transcribe(local_path)
                        logger.info(
                            "STT result: length=%d, text=%.200s",
                            len(text) if text else 0,
                            text or "",
                        )
                        if text:
                            parsed_parts.append(f"[Транскрипция аудио]:\n{text}")
                    finally:
                        os.unlink(local_path)
                elif category == "document":
                    try:
                        if file_type:
                            text = process_document(local_path, file_type)
                        else:
                            text = None
                        if text:
                            parsed_parts.append(f"[Содержимое документа]:\n{text}")
                    finally:
                        os.unlink(local_path)
                else:
                    logger.warning("Unknown file category for %s, skipping", file_id)
            except Exception as exc:
                logger.warning(
                    "Failed to parse file %s (%s): %s",
                    file_id,
                    category,
                    exc,
                    exc_info=True,
                )

    finally:
        await adapter.aclose()
        if stt is not None:
            await stt.aclose()

    parsed_text = "\n\n".join(parsed_parts)
    return parsed_text, image_paths


async def _finance_ai_pipeline(
    system_prompt: str,
    combined_text: str,
    file_items: list[dict],
    bot_token: str | None,
    messenger_type: str | None,
) -> dict:
    """Single async pipeline: download + parse media + call AI."""
    image_paths: list[str] | None = None
    media_text = ""

    if file_items and bot_token and messenger_type:
        media_text, image_paths = await _download_and_parse_media(
            file_items, bot_token, messenger_type
        )
        image_paths = image_paths or None

    # Merge text from messages + parsed media
    if media_text:
        full_text = f"{combined_text}\n\n{media_text}" if combined_text else media_text
    else:
        full_text = combined_text

    if not full_text:
        if image_paths:
            full_text = "Распознай данные с прикреплённого изображения"
        else:
            parts = []
            if file_items:
                parts.append(f"{len(file_items)} file(s) failed to download or parse")
            else:
                parts.append("no text and no files")
            raise ValueError(f"No text data for processing: {'; '.join(parts)}")

    try:
        return await _ai_generate_json(
            system_prompt, full_text, image_paths=image_paths
        )
    finally:
        if image_paths:
            for p in image_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _get_file_info(mime: str | None) -> tuple[str, str]:
    """Classify file and map MIME type to extension.

    :param mime: MIME type string or None.
    :returns: Tuple of (category, extension).
    """
    if not mime:
        return "unknown", ".bin"

    # extension mapping
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/wav": ".wav",
        "audio/webm": ".webm",
        "audio/x-opus": ".opus",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }
    ext = mapping.get(mime, ".bin")

    # category classification
    if mime.startswith("image/"):
        category = "image"
    elif mime.startswith("audio/"):
        category = "audio"
    elif mime in (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        category = "document"
    else:
        category = "unknown"

    return category, ext


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

    # Type guards: all() ensures these are not None
    adapter = create_adapter(str(messenger_type), str(bot_token))

    async def _send() -> None:
        try:
            await adapter.send_file(
                chat_id=str(chat_id),
                file_path=artifact_path,
                caption="Результат обработки готов ✅",
            )
        finally:
            await adapter.aclose()
            try:
                os.unlink(artifact_path)
            except OSError:
                logger.warning("Failed to cleanup artifact: %s", artifact_path)

    asyncio.run(_send())
