import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.incoming import IncomingEnvelope
from core.interfaces.messenger import IMessengerAdapter
from core.services.otp import OTPService
from infrastructure.auth.dependencies import get_user_db
from infrastructure.database.base import Base
from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable
from infrastructure.database.session import get_db_session
from fastapi_users.db import SQLAlchemyUserDatabase
from presentation.api.main import app
from presentation.api.otp import get_otp_service


def _require_test_db_url() -> str:
    """Get TEST_DATABASE_URL or raise RuntimeError."""
    from os import environ

    url = environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. "
            "Tests must run against PostgreSQL. "
            "Set TEST_DATABASE_URL in .env or environment."
        )
    return url


# ============================================================
# PostgreSQL-only test infrastructure
# ============================================================
TEST_DATABASE_URL = _require_test_db_url()


@pytest_asyncio.fixture(scope="session")
async def pg_test_db() -> AsyncGenerator[str, None]:
    """Create a temporary PostgreSQL database for the test session.

    Creates test_{uuid}, yields its URL, then drops it.
    Requires TEST_DATABASE_URL pointing to the 'postgres' maintenance DB.
    """
    db_name = f"test_{uuid.uuid4().hex[:12]}"

    maintenance_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    f"""
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = '{db_name}'
                    AND pid <> pg_backend_pid()
                    """
                )
            )
            await conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
            await conn.execute(text(f"CREATE DATABASE {db_name}"))

        test_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + f"/{db_name}"
        yield test_url

    finally:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    f"""
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = '{db_name}'
                    AND pid <> pg_backend_pid()
                    """
                )
            )
            await conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
        await engine.dispose()


@pytest_asyncio.fixture
async def db_engine(pg_test_db: str) -> AsyncGenerator:
    """Create engine pointing to the temporary test PostgreSQL database."""
    engine = create_async_engine(pg_test_db, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session for each test."""
    async_session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def test_company(db_session: AsyncSession) -> CompanyTable:
    """Create a test company for multi-tenant tests."""
    company = CompanyTable(
        name="Test Company",
        allowed_modules=["finance", "estimator", "hr"],
    )
    db_session.add(company)
    await db_session.flush()
    return company


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[FakeAsyncRedis, None]:
    """Provide fakeredis instance for OTP tests."""
    redis = FakeAsyncRedis(decode_responses=False)
    yield redis
    await redis.aclose()


@pytest_asyncio.fixture
async def otp_service(fake_redis: FakeAsyncRedis) -> OTPService:
    """Provide OTPService with fake Redis."""
    return OTPService(fake_redis)


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    fake_redis: FakeAsyncRedis,
    mock_adapter: IMessengerAdapter,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client with database and Redis dependency overrides."""

    async def override_get_db():
        yield db_session

    async def override_get_user_db() -> AsyncGenerator[
        SQLAlchemyUserDatabase[UserTable, uuid.UUID], None
    ]:
        yield SQLAlchemyUserDatabase(db_session, UserTable)

    async def override_get_otp_service() -> OTPService:
        return OTPService(fake_redis)

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_user_db] = override_get_user_db
    app.dependency_overrides[get_otp_service] = override_get_otp_service

    # Override adapter via FastAPI dependency
    from presentation.web.pages import get_adapter

    app.dependency_overrides[get_adapter] = lambda: mock_adapter

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(
    client: AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with valid JWT token via full register → login flow.

    Idempotent: if user already exists (e.g. on persistent PostgreSQL DB),
    just proceeds to login.

    The user's company is updated to allow all module types so tests can
    create bots with any module_type.
    """
    test_email = f"auth_test_{uuid.uuid4().hex[:6]}@example.com"
    test_password = "SecureP@ss123"

    # Register user (ignore 400 if already exists)
    resp = await client.post(
        "/auth/register",
        json={
            "email": test_email,
            "password": test_password,
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )
    assert resp.status_code in (201, 400), f"Registration failed: {resp.text}"

    # Login to get JWT token
    resp = await client.post(
        "/auth/login",
        data={"username": test_email, "password": test_password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]

    # Set Authorization header for subsequent requests
    client.headers["Authorization"] = f"Bearer {token}"

    # Update the user's company to allow all module types for tests
    from sqlalchemy import select
    from infrastructure.database.models.user import UserTable
    from infrastructure.database.models.company import CompanyTable

    result = await db_session.execute(
        select(UserTable).where(UserTable.email == test_email)
    )
    user = result.scalar_one_or_none()
    if user:
        result = await db_session.execute(
            select(CompanyTable).where(CompanyTable.id == user.company_id)
        )
        company = result.scalar_one_or_none()
        if company:
            company.allowed_modules = ["finance", "estimator", "hr"]
            await db_session.flush()

    yield client


@pytest.fixture
def bot_api_headers() -> dict[str, str]:
    """Headers for bot API authentication (X-API-Key)."""
    return {"X-API-Key": "test_bot_api_key"}


# Global settings override for tests
@pytest.fixture(autouse=True)
def override_settings(monkeypatch: pytest.MonkeyPatch, pg_test_db: str) -> None:
    """Override settings for tests: secret_key, bot_api_key, and database URL."""
    monkeypatch.setattr(
        "infrastructure.config.settings.secret_key", "test_secret_key_for_jwt"
    )
    monkeypatch.setattr(
        "infrastructure.config.settings.bot_api_key", "test_bot_api_key"
    )
    monkeypatch.setattr("infrastructure.config.settings.redis_url", "redis://localhost")
    monkeypatch.setattr("infrastructure.config.settings.database_url", pg_test_db)
    monkeypatch.setattr("infrastructure.config.settings.database_sync_url", pg_test_db)


# ============================================================
# Step 2 Fixtures: Bot instance, mock adapter, hooks client
# ============================================================


@pytest_asyncio.fixture
async def test_bot_instance(
    db_session: AsyncSession, test_company: CompanyTable
) -> BotInstanceTable:
    """Create a test bot instance linked to test_company."""
    bot = BotInstanceTable(
        company_id=test_company.id,
        messenger_type="TG",
        token="test_bot_token_123",
        module_type="finance",
        status="active",
    )
    db_session.add(bot)
    await db_session.flush()
    return bot


@pytest.fixture
def mock_adapter() -> IMessengerAdapter:
    """Mock messenger adapter that records calls.

    parse_webhook returns a realistic IncomingEnvelope.
    send_text, send_file, download_file are AsyncMocks.
    """
    adapter = AsyncMock(spec=IMessengerAdapter)

    async def fake_parse_webhook(payload: dict, bot_token: str) -> IncomingEnvelope:
        """Return a realistic IncomingEnvelope from Telegram payload."""
        # 1. Check callback_query FIRST (priority over message)
        if "callback_query" in payload:
            cq = payload["callback_query"]
            return IncomingEnvelope(
                messenger_user_id=str(cq["from"]["id"]),
                chat_id=str(cq["message"]["chat"]["id"]),
                text=cq["data"],
                bot_instance_id=uuid.uuid4(),
                messenger_type="TG",
                is_callback=True,
                raw_callback_id=str(cq["id"]),
            )

        # 2. Existing logic for message / edited_message
        message = payload.get("message") or payload.get("edited_message", {})
        if not message:
            raise ValueError("No message or callback_query in webhook payload")

        chat_id = str(message["chat"]["id"])
        messenger_user_id = str(message["from"]["id"])
        text = message.get("text") or message.get("caption")

        file_id = None
        file_type = None
        file_name = None
        if "document" in message:
            doc = message["document"]
            file_id = doc["file_id"]
            file_type = doc.get("mime_type")
            file_name = doc.get("file_name")
        elif "photo" in message:
            photo = message["photo"][-1]
            file_id = photo["file_id"]
            file_type = "image/jpeg"

        return IncomingEnvelope(
            messenger_user_id=messenger_user_id,
            chat_id=chat_id,
            text=text,
            file_id=file_id,
            file_type=file_type,
            file_name=file_name,
            bot_instance_id=uuid.uuid4(),  # placeholder — router overrides
            messenger_type="TG",
        )

    adapter.parse_webhook.side_effect = fake_parse_webhook
    adapter.send_text = AsyncMock()
    adapter.send_file = AsyncMock()
    adapter.download_file = AsyncMock()
    adapter.answer_callback = AsyncMock()
    adapter.register_webhook = AsyncMock()
    adapter.aclose = AsyncMock()

    return adapter


@pytest_asyncio.fixture
async def hooks_client(
    db_session: AsyncSession,
    fake_redis: FakeAsyncRedis,
    mock_adapter: IMessengerAdapter,
    otp_service: OTPService,
) -> AsyncGenerator[AsyncClient, None]:
    """Client with HookRouterService wired to mock_adapter via dependency overrides."""
    from core.services.session import SessionService
    from infrastructure.services.messenger_link import MessengerLinkService

    session_service = SessionService(fake_redis)
    messenger_link_service = MessengerLinkService(otp_service, db_session)

    async def override_get_db():
        yield db_session

    async def override_get_user_db() -> AsyncGenerator[
        SQLAlchemyUserDatabase[UserTable, uuid.UUID], None
    ]:
        yield SQLAlchemyUserDatabase(db_session, UserTable)

    async def override_get_otp_service() -> OTPService:
        return otp_service

    async def override_get_session_service() -> SessionService:
        return session_service

    async def override_get_messenger_link_service() -> MessengerLinkService:
        return messenger_link_service

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_user_db] = override_get_user_db
    app.dependency_overrides[get_otp_service] = override_get_otp_service

    # For hooks endpoint — inject mock_adapter into hooks.py
    from presentation.api import hooks as hooks_module

    async def override_get_messenger_link_service_for_hooks() -> MessengerLinkService:
        return messenger_link_service

    async def override_get_session_service_for_hooks() -> SessionService:
        return session_service

    async def override_get_otp_service_for_hooks() -> OTPService:
        return otp_service

    async def override_get_db_for_hooks():
        yield db_session

    async def _override_get_db_session():
        yield db_session

    hooks_module.get_db_session = _override_get_db_session  # ty: ignore[invalid-assignment]

    from presentation.api.hooks import (
        get_messenger_link_service,
        get_otp_service as hooks_get_otp_service,
        get_session_service,
    )

    app.dependency_overrides[get_messenger_link_service] = (
        override_get_messenger_link_service_for_hooks
    )
    app.dependency_overrides[hooks_get_otp_service] = override_get_otp_service_for_hooks
    app.dependency_overrides[get_session_service] = (
        override_get_session_service_for_hooks
    )

    # Override adapter creation in hook_router (where create_adapter is imported)
    import infrastructure.services.hook_router as hook_router_module

    original_create_adapter = hook_router_module.create_adapter

    def _override_create_adapter(
        messenger_type: str, bot_token: str
    ) -> IMessengerAdapter:
        return mock_adapter

    hook_router_module.create_adapter = _override_create_adapter  # ty: ignore[invalid-assignment]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    hook_router_module.create_adapter = original_create_adapter
