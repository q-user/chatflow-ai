from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.config import settings

# ── Async engine (for FastAPI) — lazy init ──
_async_engine: Any = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_async_engine():
    """Lazily create async engine on first use."""
    global _async_engine, async_session_factory

    if _async_engine is None:
        _async_engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
        async_session_factory = async_sessionmaker(
            bind=_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    return _async_engine


async def get_db_session() -> AsyncGenerator[AsyncSession, Any]:
    """FastAPI dependency that yields a database session."""
    get_async_engine()
    factory = async_session_factory
    assert factory is not None
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Sync engine (for Celery tasks) ──
# Lazily created — only needed when running Celery workers.
# Deferred to avoid requiring psycopg2 at import time in tests.
_sync_url: str | None = None
sync_engine: Any = None
sync_session_factory: Any = None


def _init_sync_engine() -> None:
    """Initialize sync engine on first use.

    Raises RuntimeError if sync engine cannot be initialized
    (e.g. missing psycopg2 driver in the environment).
    """
    global sync_engine, sync_session_factory, _sync_url

    if sync_engine is not None:
        return

    try:
        _sync_url = settings.database_sync_url or settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"
        )
        sync_engine = create_engine(
            _sync_url,
            echo=settings.debug,
            pool_pre_ping=True,
        )
        sync_session_factory = sessionmaker(
            bind=sync_engine,
            class_=Session,
            expire_on_commit=False,
        )
    except Exception as exc:
        sync_engine = None
        sync_session_factory = None
        raise RuntimeError(
            f"Failed to initialize sync DB engine: {exc}. "
            "Ensure psycopg2-binary is installed and DATABASE_SYNC_URL is set correctly."
        ) from exc
