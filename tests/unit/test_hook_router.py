"""Unit tests for HookRouterService — webhook processing pipeline."""

import uuid
from collections.abc import Generator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.incoming import IncomingEnvelope
from core.interfaces.messenger import IMessengerAdapter
from core.services.otp import OTPService
from core.services.session import SessionService
from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable
from infrastructure.services.hook_router import HookRouterService
from infrastructure.services.messenger_link import MessengerLinkService


@pytest.fixture
def hook_router(
    db_session: AsyncSession,
    fake_redis: FakeAsyncRedis,
    otp_service,
    session_service: SessionService,
    messenger_link_service: MessengerLinkService,
    mock_adapter,
) -> Generator[HookRouterService, None, None]:
    """HookRouterService wired to mock adapter via adapter_factory injection."""

    def mock_adapter_factory(messenger_type: str, bot_token: str) -> IMessengerAdapter:
        return mock_adapter

    service = HookRouterService(
        session=db_session,
        redis=fake_redis,
        otp_service=otp_service,
        session_service=session_service,
        messenger_link_service=messenger_link_service,
        adapter_factory=mock_adapter_factory,
    )

    yield service


@pytest_asyncio.fixture
async def session_service(fake_redis: FakeAsyncRedis) -> SessionService:
    """Provide SessionService with fake Redis."""
    return SessionService(fake_redis)


@pytest_asyncio.fixture
async def messenger_link_service(
    otp_service: OTPService, db_session: AsyncSession
) -> MessengerLinkService:
    """Provide MessengerLinkService with fake OTP and DB session."""
    return MessengerLinkService(otp_service, db_session)


@pytest_asyncio.fixture
async def finance_bot_instance(
    db_session: AsyncSession, test_company: CompanyTable
) -> BotInstanceTable:
    """Create a test bot instance with module_type=finance."""
    bot = BotInstanceTable(
        company_id=test_company.id,
        messenger_type="TG",
        token="finance_bot_token_123",
        module_type="finance",
        status="active",
    )
    db_session.add(bot)
    await db_session.flush()
    return bot


def _make_unique_id() -> str:
    """Generate a unique suffix for test data to avoid conflicts across runs."""
    return uuid.uuid4().hex[:8]


def _make_user(email_prefix: str, company_id, telegram_id: str) -> UserTable:
    """Create a test user with unique identifiers."""
    return UserTable(
        email=f"{email_prefix}_{_make_unique_id()}@example.com",
        hashed_password="pass",
        company_id=company_id,
        telegram_id=telegram_id,
    )


def _tg_text_payload(telegram_id: str, text: str) -> dict:
    """Build a Telegram message payload."""
    return {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": text,
        }
    }


# ──────────────────────────────────────────────
# Bot lookup validation tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_webhook_bot_not_found(hook_router: HookRouterService):
    """Bot not found → 404."""
    status_code, message = await hook_router.process_webhook(
        "TG", uuid.uuid4(), {"message": {}}
    )
    assert status_code == 404
    assert "not found" in message.lower()


@pytest.mark.asyncio
async def test_process_webhook_messenger_type_mismatch(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
):
    """messenger_type doesn't match BotInstance → 403."""
    status_code, message = await hook_router.process_webhook(
        "YM",  # BotInstance is "TG"
        uuid.UUID(str(test_bot_instance.id)),
        {"message": {"chat": {"id": 123}, "from": {"id": 456}, "text": "hello"}},
    )
    assert status_code == 403
    assert "mismatch" in message.lower()


@pytest.mark.asyncio
async def test_process_webhook_bot_inactive(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    db_session: AsyncSession,
    mock_adapter,
):
    """BotInstance.status = inactive → 403."""
    test_bot_instance.status = "inactive"
    await db_session.commit()

    status_code, message = await hook_router.process_webhook(
        "TG",
        uuid.UUID(str(test_bot_instance.id)),
        {"message": {"chat": {"id": 123}, "from": {"id": 456}, "text": "hello"}},
    )
    assert status_code == 403
    assert "inactive" in message.lower()


@pytest.mark.asyncio
async def test_process_webhook_invalid_payload(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
):
    """Payload without message → 400."""
    mock_adapter.parse_webhook.side_effect = ValueError("No message in webhook payload")

    status_code, message = await hook_router.process_webhook(
        "TG",
        uuid.UUID(str(test_bot_instance.id)),
        {"update_id": 123},
    )
    assert status_code == 400
    assert "invalid" in message.lower()


# ──────────────────────────────────────────────
# Unknown user tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_webhook_unknown_user_non_otp(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
):
    """Unknown user, non-OTP message → sends UNLINKED_PROMPT."""
    payload = {
        "message": {
            "chat": {"id": 999888777},
            "from": {"id": 999888777},
            "text": "hello bot!",
        }
    }

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert (
        "не привязан" in call_args[0][1].lower()
        or "личный кабинет" in call_args[0][1].lower()
    )


@pytest.mark.asyncio
async def test_process_webhook_unknown_user_invalid_otp(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
):
    """Unknown user, invalid OTP code → sends OTP_FAILURE."""
    payload = {
        "message": {
            "chat": {"id": 999888777},
            "from": {"id": 999888777},
            "text": "000000",
        }
    }

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert (
        "неверный" in call_args[0][1].lower() or "попробуйте" in call_args[0][1].lower()
    )


@pytest.mark.asyncio
async def test_process_webhook_unknown_user_valid_otp(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    fake_redis: FakeAsyncRedis,
    otp_service,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Unknown user, valid OTP code → links messenger, sends OTP_SUCCESS."""
    user = UserTable(
        email=f"otp_user_{_make_unique_id()}@example.com",
        hashed_password="pass",
        company_id=test_company.id,
    )
    db_session.add(user)
    await db_session.flush()

    code = await otp_service.generate_code(user.id)

    messenger_id = f"777666555_{_make_unique_id()}"
    payload = {
        "message": {
            "chat": {"id": messenger_id},
            "from": {"id": messenger_id},
            "text": code,
        }
    }

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    await db_session.refresh(user)
    assert user.telegram_id == messenger_id

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "привязан" in call_args[0][1].lower()


# ──────────────────────────────────────────────
# Estimator (Batch) — command tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_webhook_known_user_command_new(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Known user, /new command → starts session (estimator mode)."""
    telegram_id = f"111222333_{_make_unique_id()}"
    user = _make_user("new_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/new")

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "сессия начата" in call_args[0][1].lower()


@pytest.mark.asyncio
async def test_process_webhook_known_user_command_compile(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
    session_service: SessionService,
):
    """Known user, /compile with active session → compiles and sends result (estimator)."""
    telegram_id = f"444555666_{_make_unique_id()}"
    user = _make_user("compile_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    await session_service.handle_new(user.id)
    await session_service.accumulate(
        user.id,
        IncomingEnvelope(
            messenger_user_id=telegram_id,
            chat_id=telegram_id,
            text="some data",
            bot_instance_id=uuid.UUID(str(test_bot_instance.id)),
            messenger_type="TG",
        ),
    )

    payload = _tg_text_payload(telegram_id, "/compile")

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "принято" in call_args[0][1].lower() or "элемент" in call_args[0][1].lower()


@pytest.mark.asyncio
async def test_process_webhook_known_user_command_compile_no_session(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Known user, /compile without session → sends error (estimator)."""
    telegram_id = f"777888999_{_make_unique_id()}"
    user = _make_user("no_session_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/compile")

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "нет активной сессии" in call_args[0][1].lower()


@pytest.mark.asyncio
async def test_process_webhook_known_user_unknown_command(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Known user, unknown command → sends 'unknown command' (estimator)."""
    telegram_id = f"123123123_{_make_unique_id()}"
    user = _make_user("unknown_cmd_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/unknown")

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "неизвестная команда" in call_args[0][1].lower()


# ──────────────────────────────────────────────
# Estimator (Batch) — text message tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_webhook_known_user_text_collecting(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
    session_service: SessionService,
):
    """Known user, text while collecting → accumulates (estimator)."""
    telegram_id = f"321321321_{_make_unique_id()}"
    user = _make_user("collecting_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    await session_service.handle_new(user.id)

    payload = _tg_text_payload(telegram_id, "some data to collect")

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "принято" in call_args[0][1].lower()


@pytest.mark.asyncio
async def test_process_webhook_known_user_text_idle(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Known user, text while idle → sends 'send /new' (estimator)."""
    telegram_id = f"654654654_{_make_unique_id()}"
    user = _make_user("idle_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "hello")

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "/new" in call_args[0][1]


# ──────────────────────────────────────────────
# Adapter lifecycle test
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_webhook_adapter_closed(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
):
    """Adapter must be closed regardless of outcome."""
    payload = _tg_text_payload("123", "hello")
    await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert mock_adapter.aclose.call_count == 1

    mock_adapter.aclose.reset_mock()
    mock_adapter.parse_webhook.side_effect = ValueError("Invalid")
    await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert mock_adapter.aclose.call_count == 1


# ──────────────────────────────────────────────
# Finance (Stream) — dispatch tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finance_text_enqueues_process_stream_item(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: text message → enqueues process_stream_item."""
    telegram_id = f"fin_text_{_make_unique_id()}"
    user = _make_user("fin_text_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "Обед 350р")

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )

    assert status_code == 200
    mock_celery.send_task.assert_called_once()
    call_kwargs = mock_celery.send_task.call_args
    assert call_kwargs[0][0] == "process_stream_item"
    snapshot = call_kwargs[1]["kwargs"]["snapshot"]
    assert len(snapshot["items"]) == 1
    assert snapshot["items"][0]["text"] == "Обед 350р"

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "анализирую" in call_args[0][1].lower()


@pytest.mark.asyncio
async def test_finance_file_enqueues_process_stream_item(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: file message → enqueues process_stream_item with file metadata."""
    telegram_id = f"fin_file_{_make_unique_id()}"
    user = _make_user("fin_file_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": "Чек из магазина",
            "document": {"file_id": "file123", "mime_type": "image/jpeg"},
        }
    }

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )

    assert status_code == 200
    mock_celery.send_task.assert_called_once()
    snapshot = mock_celery.send_task.call_args[1]["kwargs"]["snapshot"]
    assert snapshot["items"][0]["text"] == "Чек из магазина"
    assert snapshot["items"][0]["file_id"] == "file123"
    assert snapshot["items"][0]["file_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_finance_report_enqueues_generate_report(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: /report → enqueues generate_report with default 7d period."""
    telegram_id = f"fin_report_{_make_unique_id()}"
    user = _make_user("fin_report_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/report")

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )

    assert status_code == 200
    mock_celery.send_task.assert_called_once()
    call_kwargs = mock_celery.send_task.call_args
    assert call_kwargs[0][0] == "generate_report"
    kw = call_kwargs[1]["kwargs"]
    assert kw["user_id"] == str(user.id)
    assert kw["chat_id"] == telegram_id
    assert kw["period_days"] == 7
    assert "date_from" in kw
    assert "date_to" in kw

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "отчёт" in call_args[0][1].lower() or "формиров" in call_args[0][1].lower()


@pytest.mark.asyncio
async def test_finance_report_with_period_1d(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: /report 1d → enqueues generate_report with period_days=1."""
    telegram_id = f"fin_r1d_{_make_unique_id()}"
    user = _make_user("fin_r1d_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/report 1d")

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )

    assert status_code == 200
    kw = mock_celery.send_task.call_args[1]["kwargs"]
    assert kw["period_days"] == 1


@pytest.mark.asyncio
async def test_finance_report_with_period_1w(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: /report 1w → enqueues generate_report with period_days=7."""
    telegram_id = f"fin_r1w_{_make_unique_id()}"
    user = _make_user("fin_r1w_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/report 1w")

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )

    assert status_code == 200
    kw = mock_celery.send_task.call_args[1]["kwargs"]
    assert kw["period_days"] == 7


@pytest.mark.asyncio
async def test_finance_report_with_period_1m(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: /report 1m → enqueues generate_report with period_days=30."""
    telegram_id = f"fin_r1m_{_make_unique_id()}"
    user = _make_user("fin_r1m_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/report 1m")

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )

    assert status_code == 200
    kw = mock_celery.send_task.call_args[1]["kwargs"]
    assert kw["period_days"] == 30


@pytest.mark.asyncio
async def test_finance_report_with_period_3m(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: /report 3m → enqueues generate_report with period_days=90."""
    telegram_id = f"fin_r3m_{_make_unique_id()}"
    user = _make_user("fin_r3m_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "/report 3m")

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )

    assert status_code == 200
    kw = mock_celery.send_task.call_args[1]["kwargs"]
    assert kw["period_days"] == 90


@pytest.mark.asyncio
async def test_finance_unknown_command_returns_help(
    hook_router: HookRouterService,
    finance_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Finance: /new, /compile, /start → help message with /report usage."""
    for cmd in ["/new", "/compile", "/start"]:
        mock_adapter.send_text.reset_mock()

        telegram_id = f"fin_unk_{_make_unique_id()}"
        user = _make_user(f"fin_unk_{cmd.strip('/')}", test_company.id, telegram_id)
        db_session.add(user)
        await db_session.flush()

        payload = _tg_text_payload(telegram_id, cmd)

        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(finance_bot_instance.id)), payload
        )
        assert status_code == 200

        mock_adapter.send_text.assert_called_once()
        call_args = mock_adapter.send_text.call_args
        msg = call_args[0][1].lower()
        assert "/report" in msg


# ──────────────────────────────────────────────
# _parse_report_period unit tests
# ──────────────────────────────────────────────


def test_parse_report_period_default():
    period_days, date_from, date_to = HookRouterService._parse_report_period("/report")
    assert period_days == 7
    assert date_from < date_to


def test_parse_report_period_1d():
    period_days, _, _ = HookRouterService._parse_report_period("/report 1d")
    assert period_days == 1


def test_parse_report_period_2w():
    period_days, _, _ = HookRouterService._parse_report_period("/report 2w")
    assert period_days == 14


def test_parse_report_period_3m():
    period_days, _, _ = HookRouterService._parse_report_period("/report 3m")
    assert period_days == 90


def test_parse_report_period_invalid_unit_falls_back_to_default():
    period_days, _, _ = HookRouterService._parse_report_period("/report 5y")
    assert period_days == 7


def test_parse_report_period_garbage_falls_back_to_default():
    period_days, _, _ = HookRouterService._parse_report_period("/report abc")
    assert period_days == 7


# ──────────────────────────────────────────────
# Module-type routing test
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_module_type_returns_error(
    hook_router: HookRouterService,
    db_session: AsyncSession,
    test_company: CompanyTable,
    mock_adapter,
):
    """Unknown module_type → sends error to user."""
    bot = BotInstanceTable(
        company_id=test_company.id,
        messenger_type="TG",
        token="unknown_module_bot",
        module_type="nonexistent",
        status="active",
    )
    db_session.add(bot)
    await db_session.flush()

    telegram_id = f"unk_mod_{_make_unique_id()}"
    user = _make_user("unk_mod_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "hello")

    status_code, _ = await hook_router.process_webhook(
        "TG", uuid.UUID(str(bot.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert (
        "неизвест" in call_args[0][1].lower()
        or "администратор" in call_args[0][1].lower()
    )


# ──────────────────────────────────────────────
# T9: OTP intercept does not dispatch to session
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_otp_does_not_dispatch_to_session(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """OTP from unknown user → handles OTP but never dispatches to session."""
    payload = {
        "message": {
            "chat": {"id": 111222333},
            "from": {"id": 111222333},
            "text": "123456",
        }
    }

    with patch.object(hook_router, "_dispatch_to_session") as mock_dispatch:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(test_bot_instance.id)), payload
        )

    assert status_code == 200
    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_known_user_otp_dispatches_to_session(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """OTP from known user → dispatches to session as regular message."""
    telegram_id = f"otp_known_{_make_unique_id()}"
    user = _make_user("otp_known_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = _tg_text_payload(telegram_id, "123456")

    with patch("infrastructure.services.hook_router.celery_app") as mock_celery:
        status_code, _ = await hook_router.process_webhook(
            "TG", uuid.UUID(str(test_bot_instance.id)), payload
        )

    assert status_code == 200
    mock_celery.send_task.assert_called_once()
