"""Unit tests for SessionService (Redis-based FSM)."""

import uuid

import pytest
from fakeredis import FakeAsyncRedis

from core.domain.incoming import IncomingEnvelope
from core.services.session import SessionService


@pytest.fixture
def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=False)


@pytest.fixture
def session_service(fake_redis: FakeAsyncRedis) -> SessionService:
    return SessionService(fake_redis)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def envelope(user_id: uuid.UUID) -> IncomingEnvelope:
    return IncomingEnvelope(
        messenger_user_id="123456",
        chat_id="789",
        text="Test message",
        file_id=None,
        file_type=None,
        file_name=None,
        bot_instance_id=uuid.uuid4(),
        messenger_type="TG",
    )


@pytest.mark.asyncio
async def test_handle_new_creates_collecting_state(
    session_service: SessionService, user_id: uuid.UUID
):
    """handle_new → state = collecting."""
    await session_service.handle_new(user_id)
    state = await session_service.get_state(user_id)
    assert state == "collecting"


@pytest.mark.asyncio
async def test_handle_new_resets_existing_session(
    session_service: SessionService, user_id: uuid.UUID
):
    """handle_new during existing session → resets everything."""
    # Accumulate some data
    env = IncomingEnvelope(
        messenger_user_id="123",
        chat_id="456",
        text="Old data",
        bot_instance_id=uuid.uuid4(),
        messenger_type="TG",
    )
    await session_service.handle_new(user_id)
    await session_service.accumulate(user_id, env)

    # Reset
    await session_service.handle_new(user_id)

    # Should be collecting with empty payload
    state = await session_service.get_state(user_id)
    assert state == "collecting"

    snapshot = await session_service.handle_compile(user_id)
    assert snapshot is not None
    assert len(snapshot.items) == 0


@pytest.mark.asyncio
async def test_accumulate_adds_item_to_payload(
    session_service: SessionService, user_id: uuid.UUID, envelope: IncomingEnvelope
):
    """accumulate → item added to payload list."""
    await session_service.handle_new(user_id)
    await session_service.accumulate(user_id, envelope)

    snapshot = await session_service.handle_compile(user_id)
    assert snapshot is not None
    assert len(snapshot.items) == 1
    assert snapshot.items[0]["text"] == "Test message"


@pytest.mark.asyncio
async def test_accumulate_multiple_items(
    session_service: SessionService, user_id: uuid.UUID, envelope: IncomingEnvelope
):
    """Multiple accumulate → multiple items in payload."""
    await session_service.handle_new(user_id)
    await session_service.accumulate(user_id, envelope)

    envelope2 = IncomingEnvelope(
        messenger_user_id="123456",
        chat_id="789",
        text="Second message",
        file_id="file_123",
        file_type="application/pdf",
        file_name="report.pdf",
        bot_instance_id=uuid.uuid4(),
        messenger_type="TG",
    )
    await session_service.accumulate(user_id, envelope2)

    snapshot = await session_service.handle_compile(user_id)
    assert snapshot is not None
    assert len(snapshot.items) == 2
    assert snapshot.items[1]["text"] == "Second message"
    assert snapshot.items[1]["file_id"] == "file_123"


@pytest.mark.asyncio
async def test_compile_clears_session(
    session_service: SessionService, user_id: uuid.UUID, envelope: IncomingEnvelope
):
    """handle_compile → session keys deleted."""
    await session_service.handle_new(user_id)
    await session_service.accumulate(user_id, envelope)

    snapshot = await session_service.handle_compile(user_id)
    assert snapshot is not None

    # Session should be cleared
    state = await session_service.get_state(user_id)
    assert state is None

    # Second compile → None (no active session)
    snapshot2 = await session_service.handle_compile(user_id)
    assert snapshot2 is None


@pytest.mark.asyncio
async def test_compile_without_session_returns_none(
    session_service: SessionService, user_id: uuid.UUID
):
    """handle_compile without handle_new → None."""
    snapshot = await session_service.handle_compile(user_id)
    assert snapshot is None


@pytest.mark.asyncio
async def test_get_state_returns_none_for_new_user(
    session_service: SessionService, user_id: uuid.UUID
):
    """get_state for user without session → None."""
    state = await session_service.get_state(user_id)
    assert state is None


@pytest.mark.asyncio
async def test_ttl_is_set_on_session_keys(
    session_service: SessionService, user_id: uuid.UUID
):
    """handle_new sets TTL on state key."""
    await session_service.handle_new(user_id)
    ttl = await session_service._redis.ttl(f"session:{user_id}:state")
    assert ttl > 0
    assert ttl <= SessionService.SESSION_TTL
