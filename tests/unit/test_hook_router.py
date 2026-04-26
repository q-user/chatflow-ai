"""Unit tests for HookRouterService — webhook processing pipeline."""

import uuid
from collections.abc import Generator

import pytest
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


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=False)


@pytest.fixture
def otp_service(fake_redis: FakeAsyncRedis) -> OTPService:
    return OTPService(fake_redis)


@pytest.fixture
def session_service(fake_redis: FakeAsyncRedis) -> SessionService:
    return SessionService(fake_redis)


@pytest.fixture
def messenger_link_service(
    otp_service: OTPService, db_session: AsyncSession
) -> MessengerLinkService:
    return MessengerLinkService(otp_service, db_session)


@pytest.fixture
def hook_router(
    db_session: AsyncSession,
    fake_redis: FakeAsyncRedis,
    otp_service: OTPService,
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
        {"update_id": 123},  # no message key
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

    # verify send_text was called with UNLINKED_PROMPT
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
    fake_redis: FakeAsyncRedis,
):
    """Unknown user, invalid OTP code → sends OTP_FAILURE."""
    # No OTP generated for this code
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
    otp_service: OTPService,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Unknown user, valid OTP code → links messenger, sends OTP_SUCCESS."""
    # 1. Create user in DB
    user = UserTable(
        email=f"otp_user_{_make_unique_id()}@example.com",
        hashed_password="pass",
        company_id=test_company.id,
    )
    db_session.add(user)
    await db_session.flush()

    # 2. Generate OTP for this user
    code = await otp_service.generate_code(user.id)

    # 3. Send OTP code as message from unknown messenger_user_id
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

    # 4. Verify messenger was linked
    await db_session.refresh(user)
    assert user.telegram_id == messenger_id

    # 5. Verify success message was sent
    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "привязан" in call_args[0][1].lower()


# ──────────────────────────────────────────────
# Known user — command tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_webhook_known_user_command_new(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Known user, /new command → starts session."""
    telegram_id = f"111222333_{_make_unique_id()}"
    user = _make_user("new_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": "/new",
        }
    }

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
    """Known user, /compile with active session → compiles and sends result."""
    telegram_id = f"444555666_{_make_unique_id()}"
    user = _make_user("compile_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    # Start a session first
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

    payload = {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": "/compile",
        }
    }

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
    """Known user, /compile without session → sends error."""
    telegram_id = f"777888999_{_make_unique_id()}"
    user = _make_user("no_session_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": "/compile",
        }
    }

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
    """Known user, unknown command → sends 'unknown command'."""
    telegram_id = f"123123123_{_make_unique_id()}"
    user = _make_user("unknown_cmd_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": "/unknown",
        }
    }

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "неизвестная команда" in call_args[0][1].lower()


# ──────────────────────────────────────────────
# Known user — text message tests
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
    """Known user, text while collecting → accumulates."""
    telegram_id = f"321321321_{_make_unique_id()}"
    user = _make_user("collecting_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    # Start session
    await session_service.handle_new(user.id)

    payload = {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": "some data to collect",
        }
    }

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
    """Known user, text while idle → sends 'send /new'."""
    telegram_id = f"654654654_{_make_unique_id()}"
    user = _make_user("idle_user", test_company.id, telegram_id)
    db_session.add(user)
    await db_session.flush()

    payload = {
        "message": {
            "chat": {"id": telegram_id},
            "from": {"id": telegram_id},
            "text": "hello",
        }
    }

    status_code, message = await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert status_code == 200

    mock_adapter.send_text.assert_called_once()
    call_args = mock_adapter.send_text.call_args
    assert "/new" in call_args[0][1]


@pytest.mark.asyncio
async def test_process_webhook_adapter_closed(
    hook_router: HookRouterService,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
):
    """Adapter must be closed regardless of outcome."""
    # Case 1: Success
    payload = {
        "message": {
            "chat": {"id": 123},
            "from": {"id": 456},
            "text": "hello",
        }
    }
    await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert mock_adapter.aclose.call_count == 1

    # Case 2: Invalid payload (failure)
    mock_adapter.aclose.reset_mock()
    mock_adapter.parse_webhook.side_effect = ValueError("Invalid")
    await hook_router.process_webhook(
        "TG", uuid.UUID(str(test_bot_instance.id)), payload
    )
    assert mock_adapter.aclose.call_count == 1
