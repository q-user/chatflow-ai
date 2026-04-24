"""Webhook processing orchestration service.

Lookups BotInstance, parses payload via adapter, resolves user,
and either intercepts OTP or dispatches to SessionService.

This service lives in infrastructure because it depends on SQLAlchemy models.
"""

import logging
import uuid
from typing import Any

from kombu.exceptions import OperationalError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.incoming import IncomingEnvelope
from core.domain.messenger import MESSENGER_TYPE_TO_FIELD
from core.interfaces.messenger import IMessengerAdapter
from core.services.otp import OTPService
from core.services.session import SessionService
from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.user import UserTable
from infrastructure.messengers import create_adapter
from infrastructure.services.messenger_link import MessengerLinkService
from infrastructure.task_queue.celery_app import celery_app

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
    ) -> None:
        self._session = session
        self._redis = redis
        self._otp_service = otp_service
        self._session_service = session_service
        self._messenger_link_service = messenger_link_service

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    async def process_webhook(
        self,
        messenger_type: str,
        bot_uuid: uuid.UUID,
        payload: dict[str, Any],
    ) -> tuple[int, str]:
        """Process an incoming webhook.

        :returns: (status_code, message)
        """
        # 1. Lookup BotInstance
        bot = await self._session.get(BotInstanceTable, bot_uuid)
        if bot is None:
            return 404, "Bot not found"

        # 2. Validate messenger_type and status
        if bot.messenger_type != messenger_type:
            return 403, "Messenger type mismatch"

        if bot.status != "active":
            return 403, "Bot instance is inactive"

        # 3. Create adapter for this bot instance (lazy creation)
        adapter = create_adapter(messenger_type, bot.token)

        try:
            # 4. Parse payload via adapter
            try:
                envelope = await adapter.parse_webhook(payload, bot.token)
            except (ValueError, KeyError) as e:
                logger.warning("Failed to parse webhook: %s", e)
                return 400, "Invalid webhook payload"

            # 5. Inject real bot_instance_id (adapter uses placeholder)
            # Use model_copy for immutability instead of direct mutation
            envelope = envelope.model_copy(
                update={"bot_instance_id": uuid.UUID(str(bot.id))}
            )

            # 6. Resolve user
            user = await self._resolve_user(envelope, uuid.UUID(str(bot.company_id)))
            if user is None:
                await self._handle_unknown_user(envelope, bot, adapter)
                return 200, "OK"

            # 7. Dispatch to session FSM
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
                await adapter.send_text(envelope.chat_id, OTP_SUCCESS)
            else:
                await adapter.send_text(envelope.chat_id, OTP_FAILURE)
        except ValueError:
            logger.warning("Failed to send OTP result message")

    async def _safe_send(
        self, adapter: IMessengerAdapter, chat_id: str, text: str
    ) -> None:
        """Send text message, logging network errors instead of propagating."""
        try:
            await adapter.send_text(chat_id, text)
        except ValueError as e:
            logger.warning("Failed to send message to chat %s: %s", chat_id, e)

    async def _dispatch_to_session(
        self,
        envelope: IncomingEnvelope,
        user: UserTable,
        bot: BotInstanceTable,
        adapter: IMessengerAdapter,
    ) -> None:
        """Route to SessionService based on command/payload."""
        # Answer callback first (dismiss button loading state)
        if envelope.is_callback and envelope.raw_callback_id:
            try:
                await adapter.answer_callback(envelope.raw_callback_id)
            except ValueError:
                logger.warning("Failed to answer callback")

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

    @staticmethod
    def _get_messenger_field(messenger_type: str) -> str | None:
        """Map messenger type to UserTable column name."""
        return MESSENGER_TYPE_TO_FIELD.get(messenger_type)
