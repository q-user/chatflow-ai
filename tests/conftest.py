import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.services.otp import OTPService
from infrastructure.auth.dependencies import get_user_db
from infrastructure.database.base import Base
from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable
from infrastructure.database.session import get_db_session
from fastapi_users.db import SQLAlchemyUserDatabase
from presentation.api.main import app
from presentation.api.otp import get_otp_service


# ============================================================
# Database selection: PostgreSQL (if TEST_DATABASE_URL set) or SQLite fallback
# ============================================================
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
USE_POSTGRESQL = TEST_DATABASE_URL is not None


@pytest_asyncio.fixture(scope="session")
async def pg_test_db():
    """Create a temporary PostgreSQL database for the test session.

    Creates test_{uuid}, yields its URL, then drops it.
    Requires TEST_DATABASE_URL pointing to the 'postgres' maintenance DB.
    """
    if not USE_POSTGRESQL:
        yield None
        return

    db_name = f"test_{uuid.uuid4().hex[:12]}"

    # Connect to maintenance DB to create/drop test database
    maintenance_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            # Kill existing connections to the test db (idempotent)
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
            # Disconnect all sessions from test db before dropping
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
async def db_engine(pg_test_db):
    """Create a fresh database engine — PostgreSQL or SQLite."""
    if USE_POSTGRESQL and pg_test_db:
        # PostgreSQL: create tables via metadata
        engine = create_async_engine(pg_test_db, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        # SQLite fallback: in-memory
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            echo=False,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        if not (USE_POSTGRESQL and pg_test_db):
            # Only drop tables for SQLite — PG db is dropped at session end
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
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
    company = CompanyTable(name="Test Company")
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
async def client(db_session: AsyncSession, fake_redis: FakeAsyncRedis) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client with database and Redis dependency overrides."""

    async def override_get_db():
        yield db_session

    async def override_get_user_db() -> AsyncGenerator[SQLAlchemyUserDatabase[UserTable, uuid.UUID], None]:
        yield SQLAlchemyUserDatabase(db_session, UserTable)

    async def override_get_otp_service() -> OTPService:
        return OTPService(fake_redis)

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_user_db] = override_get_user_db
    app.dependency_overrides[get_otp_service] = override_get_otp_service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with valid JWT token via full register → login flow."""
    # Register user
    resp = await client.post(
        "/auth/register",
        json={
            "email": "auth_test@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )
    assert resp.status_code == 201, f"Registration failed: {resp.text}"

    # Login to get JWT token
    resp = await client.post(
        "/auth/login",
        data={"username": "auth_test@example.com", "password": "SecureP@ss123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]

    # Set Authorization header for subsequent requests
    client.headers["Authorization"] = f"Bearer {token}"

    yield client


@pytest.fixture
def bot_api_headers() -> dict[str, str]:
    """Headers for bot API authentication (X-API-Key)."""
    return {"X-API-Key": "test_bot_api_key"}


# Global settings override for tests
@pytest.fixture(autouse=True)
def override_settings(monkeypatch: pytest.MonkeyPatch, pg_test_db: str | None) -> None:
    """Override settings for tests: secret_key, bot_api_key, and database URL."""
    monkeypatch.setattr("infrastructure.config.settings.secret_key", "test_secret_key_for_jwt")
    monkeypatch.setattr("infrastructure.config.settings.bot_api_key", "test_bot_api_key")
    monkeypatch.setattr("infrastructure.config.settings.redis_url", "redis://localhost")

    if USE_POSTGRESQL and pg_test_db:
        monkeypatch.setattr("infrastructure.config.settings.database_url", pg_test_db)
        monkeypatch.setattr("infrastructure.config.settings.database_sync_url", pg_test_db)
    else:
        monkeypatch.setattr("infrastructure.config.settings.database_url", "sqlite+aiosqlite://")
        monkeypatch.setattr("infrastructure.config.settings.database_sync_url", "sqlite+aiosqlite://")
