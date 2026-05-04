"""Webhook processing orchestration service.

Lookups BotInstance, parses payload via adapter, resolves user,
and either intercepts OTP or dispatches to SessionService.

This service lives in infrastructure because it depends on SQLAlchemy models.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from kombu.exceptions import OperationalError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.incoming import IncomingEnvelope
from core.domain.messenger import MESSENGER_TYPE_TO_FIELD
from core.interfaces.messenger import IMessengerAdapter
from core.services.otp import OTPService
from core.services.session import SessionService, SessionSnapshot
from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.user import UserTable
from infrastructure.messengers import UnsupportedMessengerError, create_adapter
from infrastructure.services.messenger_link import MessengerLinkService
from infrastructure.task_queue.celery_app import celery_app

# ============================================================
# Dependency Injection: AdapterFactory
# ============================================================

AdapterFactory = Callable[[str, str], IMessengerAdapter]


async def get_adapter_factory() -> AdapterFactory:
    """FastAPI dependency: provides the adapter factory."""
    return create_adapter


logger = logging.getLogger(__name__)

UNLINKED_PROMPT = (
    "Ваш аккаунт не привязан. "
    "Откройте личный кабинет, сгенерируйте 6-значный код и отправьте его сюда."
)
OTP_SUCCESS = "Аккаунт привязан! Теперь вы можете отправлять /new для начала работы."
OTP_FAILURE = "Неверный код. Попробуйте снова."


class HookRouterService:
    """Orchestrates webhook processing: lookup → parse → auth → dispatch."""

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        otp_service: OTPService,
        session_service: SessionService,
        messenger_link_service: MessengerLinkService,
        adapter_factory: AdapterFactory = create_adapter,
    ) -> None:
        self._session = session
        self._redis = redis
        self._otp_service = otp_service
        self._session_service = session_service
        self._messenger_link_service = messenger_link_service
        self._adapter_factory = adapter_factory

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    async def process_webhook(
        self,
        messenger_type: str,
        bot_uuid: uuid.UUID,
        payload: dict[str, Any],
        webhook_secret: str | None = None,
    ) -> tuple[int, str]:
        """Process an incoming webhook.

        :param webhook_secret: Secret token from webhook request header.
            MX: X-Max-Bot-Api-Secret, TG: X-Telegram-Bot-Api-Secret-Token.
        :returns: (status_code, message)
        """
        # 1. Lookup BotInstance
        bot = await self._session.get(BotInstanceTable, bot_uuid)
        if bot is None:
            return 404, "Bot not found"

        # 2. Authenticate webhook by messenger type
        if bot.secret:
            if webhook_secret is None or webhook_secret != bot.secret:
                logger.warning(
                    "Webhook auth failed for %s bot %s",
                    messenger_type,
                    bot_uuid,
                )
                return 401, "Invalid webhook secret"

        # 3. Validate messenger_type and status
        if bot.messenger_type != messenger_type:
            return 403, "Messenger type mismatch"

        if bot.status != "active":
            return 403, "Bot instance is inactive"

        # 3. Create adapter for this bot instance (lazy creation)
        try:
            adapter = self._adapter_factory(messenger_type, bot.token)
        except UnsupportedMessengerError as e:
            logger.warning("Unsupported messenger type %s: %s", messenger_type, e)
            return 400, f"Unsupported messenger type: {messenger_type}"

        try:
            # 4. Parse payload via adapter
            try:
                envelope = await adapter.parse_webhook(payload, bot.token)
            except (ValueError, KeyError) as e:
                logger.warning("Failed to parse webhook: %s", e)
                return 400, "Invalid webhook payload"

            # 5. Inject real bot_instance_id (adapter uses placeholder)
            envelope = envelope.model_copy(
                update={"bot_instance_id": uuid.UUID(str(bot.id))}
            )

            # 6. Resolve user
            user = await self._resolve_user(envelope, uuid.UUID(str(bot.company_id)))

            # 7. OTP intercept — for unknown users, check OTP before dispatch
            if user is None:
                await self._handle_unknown_user(envelope, bot, adapter)
                return 200, "OK"

            # 8. Dispatch to session FSM
            await self._dispatch_to_session(envelope, user, bot, adapter)
            return 200, "OK"
        finally:
            await adapter.aclose()

    # ──────────────────────────────────────────────
    # Internal pipeline
    # ──────────────────────────────────────────────

    async def _resolve_user(
        self, envelope: IncomingEnvelope, company_id: uuid.UUID
    ) -> UserTable | None:
        """Find User by messenger_user_id within company."""
        messenger_field = self._get_messenger_field(envelope.messenger_type)
        if messenger_field is None:
            return None
        stmt = (
            select(UserTable)
            .where(UserTable.company_id == company_id)
            .where(getattr(UserTable, messenger_field) == envelope.messenger_user_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_unknown_user(
        self,
        envelope: IncomingEnvelope,
        bot: BotInstanceTable,
        adapter: IMessengerAdapter,
    ) -> None:
        """OTP-intercept: if 6 digits → verify and link, else → prompt."""
        if not envelope.is_otp_pattern:
            try:
                await adapter.send_text(envelope.chat_id, UNLINKED_PROMPT)
            except ValueError:
                logger.warning("Failed to send unlinked prompt")
            return

        assert envelope.text is not None  # is_otp_pattern guarantees text

        # Use reverse OTP lookup to find user_id from code
        user_id = await self._messenger_link_service.link_by_otp(
            envelope.text,
            envelope.messenger_type,
            envelope.messenger_user_id,
        )

        try:
            if user_id is not None:
                await self._safe_send(adapter, envelope.chat_id, OTP_SUCCESS)
            else:
                await self._safe_send(adapter, envelope.chat_id, OTP_FAILURE)
        except Exception as e:
            logger.exception("Unexpected error sending OTP result: %s", e)

    async def _safe_send(
        self, adapter: IMessengerAdapter, chat_id: str, text: str
    ) -> None:
        """Send text message, logging network errors instead of propagating."""
        try:
            await adapter.send_text(chat_id, text)
        except Exception as e:
            logger.warning("Failed to send message to chat %s: %s", chat_id, e)

    async def _dispatch_to_session(
        self,
        envelope: IncomingEnvelope,
        user: UserTable,
        bot: BotInstanceTable,
        adapter: IMessengerAdapter,
    ) -> None:
        """Module-aware dispatch: estimator (Batch) vs finance (Stream)."""
        # Answer callback first (dismiss button loading state)
        if envelope.is_callback and envelope.raw_callback_id:
            try:
                await adapter.answer_callback(envelope.raw_callback_id)
            except ValueError:
                logger.warning("Failed to answer callback")

        module_type = bot.module_type
        if module_type == "estimator":
            await self._dispatch_estimator(envelope, user, bot, adapter)
        elif module_type == "finance":
            await self._dispatch_finance(envelope, user, bot, adapter)
        else:
            logger.warning("Unknown module_type=%s for bot=%s", module_type, bot.id)
            await self._safe_send(
                adapter,
                envelope.chat_id,
                "Неизвестный тип модуля. Обратитесь к администратору.",
            )

    async def _dispatch_estimator(
        self,
        envelope: IncomingEnvelope,
        user: UserTable,
        bot: BotInstanceTable,
        adapter: IMessengerAdapter,
    ) -> None:
        """Batch mode: Redis FSM with /new, /compile, accumulate."""
        state = await self._session_service.get_state(user.id)

        if envelope.is_command:
            if envelope.text == "/new":
                await self._session_service.handle_new(user.id)
                await self._safe_send(
                    adapter,
                    envelope.chat_id,
                    "Сессия начата. Отправляйте данные — текст и файлы будут накоплены. "
                    "Отправьте /compile для завершения.",
                )
                return

            if envelope.text == "/compile":
                snapshot = await self._session_service.handle_compile(user.id)
                if snapshot is None:
                    await self._safe_send(
                        adapter,
                        envelope.chat_id,
                        "Нет активной сессии. Отправьте /new для начала.",
                    )
                    return

                # Fill in missing fields from bot context (immutable model_copy)
                snapshot = snapshot.model_copy(
                    update={
                        "company_id": uuid.UUID(str(user.company_id)),
                        "bot_instance_id": uuid.UUID(str(bot.id)),
                        "module_type": bot.module_type,
                        "chat_id": envelope.chat_id,
                        "messenger_type": envelope.messenger_type,
                        "bot_token": bot.token,
                        "bot_config": bot.config,
                    }
                )

                # Enqueue to Celery for processing
                try:
                    celery_app.send_task(
                        "compile_session",
                        kwargs={"snapshot": snapshot.model_dump(mode="json")},
                    )
                except OperationalError:
                    logger.exception("Celery broker unavailable")
                    await self._safe_send(
                        adapter,
                        envelope.chat_id,
                        "Система временно недоступна. Попробуйте позже.",
                    )
                    return

                await self._safe_send(
                    adapter,
                    envelope.chat_id,
                    f"Принято {len(snapshot.items)} элементов. Обрабатываю...",
                )
                return

            await self._safe_send(
                adapter,
                envelope.chat_id,
                "Неизвестная команда. Доступные: /new, /compile",
            )
            return

        # Regular message — accumulate if collecting
        if state == "collecting":
            await self._session_service.accumulate(user.id, envelope)
            count = await self._redis.llen(  # ty: ignore[invalid-await]
                f"session:{user.id}:payload"
            )
            logger.info(
                "Accumulated item for user %s: text=%r file_id=%r file_type=%r (total=%s)",
                user.id,
                envelope.text,
                envelope.file_id,
                envelope.file_type,
                count,
            )
            await self._safe_send(
                adapter,
                envelope.chat_id,
                f"Принято ({count}). Отправьте /compile для завершения.",
            )
        else:
            await self._safe_send(
                adapter,
                envelope.chat_id,
                "Отправьте /new для начала новой сессии.",
            )

    async def _dispatch_finance(
        self,
        envelope: IncomingEnvelope,
        user: UserTable,
        bot: BotInstanceTable,
        adapter: IMessengerAdapter,
    ) -> None:
        """Stream mode: per-message AI processing + /report for CSV."""
        if envelope.is_callback:
            return

        if envelope.is_command:
            if envelope.text and envelope.text.startswith("/report"):
                period_days, date_from, date_to = self._parse_report_period(
                    envelope.text
                )
                try:
                    celery_app.send_task(
                        "generate_report",
                        kwargs={
                            "user_id": str(user.id),
                            "company_id": str(user.company_id),
                            "bot_instance_id": str(bot.id),
                            "chat_id": envelope.chat_id,
                            "messenger_type": envelope.messenger_type,
                            "bot_token": bot.token,
                            "date_from": date_from,
                            "date_to": date_to,
                            "period_days": period_days,
                        },
                    )
                    await self._safe_send(
                        adapter,
                        envelope.chat_id,
                        f"⏳ Формирую отчёт за {period_days}д...",
                    )
                except OperationalError:
                    logger.exception("Celery broker unavailable")
                    await self._safe_send(
                        adapter,
                        envelope.chat_id,
                        "Система временно недоступна. Попробуйте позже.",
                    )
                return

            await self._safe_send(
                adapter,
                envelope.chat_id,
                "Отправьте расход или чек — я обработаю. "
                "Для отчёта: /report (по умолчанию 7д), "
                "/report 1d, /report 1w, /report 1m.",
            )
            return

        # Non-command message or file → stream item
        item = {
            "text": envelope.text,
            "file_id": envelope.file_id,
            "file_type": envelope.file_type,
            "file_name": envelope.file_name,
        }
        snapshot = SessionSnapshot(
            user_id=user.id,
            company_id=uuid.UUID(str(user.company_id)),
            bot_instance_id=uuid.UUID(str(bot.id)),
            module_type=bot.module_type,
            chat_id=envelope.chat_id,
            messenger_type=envelope.messenger_type,
            bot_token=bot.token,
            bot_config=bot.config,
            items=[item],
        )
        try:
            celery_app.send_task(
                "process_stream_item",
                kwargs={"snapshot": snapshot.model_dump(mode="json")},
            )
            await self._safe_send(adapter, envelope.chat_id, "⏳ Анализирую...")
        except OperationalError:
            logger.exception("Celery broker unavailable")
            await self._safe_send(
                adapter,
                envelope.chat_id,
                "Система временно недоступна. Попробуйте позже.",
            )

    @staticmethod
    def _parse_report_period(text: str) -> tuple[int, str, str]:
        """Parse /report command and return (period_days, date_from, date_to).

        Formats:
        /report → 7 days (default)
        /report 1d → 1 day
        /report 2w → 14 days
        /report 3m → 90 days

        Period is clamped to [1, 365] days.

        :returns: (period_days, date_from ISO, date_to ISO)
        """
        match = re.match(r"^/report\s+(\d+)([dwm])", text)
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            multipliers = {"d": 1, "w": 7, "m": 30}
            period_days = value * multipliers[unit]
            period_days = max(1, min(period_days, 365))
        else:
            period_days = 7

        now = datetime.now(timezone.utc)
        date_from = (now - timedelta(days=period_days)).strftime("%Y-%m-%d")
        date_to = now.strftime("%Y-%m-%d")
        return period_days, date_from, date_to

    @staticmethod
    def _get_messenger_field(messenger_type: str) -> str | None:
        """Map messenger type to UserTable column name."""
        return MESSENGER_TYPE_TO_FIELD.get(messenger_type)
