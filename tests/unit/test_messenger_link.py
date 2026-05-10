"""Unit tests for MessengerLinkService."""

import uuid
import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.otp import OTPService
from infrastructure.services.messenger_link import MessengerLinkService
from infrastructure.database.models.user import UserTable


@pytest.fixture
def mock_otp_service():
    return AsyncMock(spec=OTPService)


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def link_service(mock_otp_service, mock_session):
    return MessengerLinkService(mock_otp_service, mock_session)


@pytest.mark.asyncio
async def test_link_by_otp_success(link_service, mock_otp_service, mock_session):
    """Successful linking: valid OTP and existing user."""
    user_id = uuid.uuid4()
    mock_otp_service.verify_code_by_value.return_value = user_id

    mock_user = UserTable(id=user_id, email="test@example.com", company_id=uuid.uuid4())
    mock_session.get.return_value = mock_user

    result = await link_service.link_by_otp(
        code="123456", messenger_type="TG", messenger_id="tg_123"
    )

    assert result == user_id
    assert mock_user.telegram_id == "tg_123"
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_by_otp_invalid_code(link_service, mock_otp_service):
    """Failure: OTP code is invalid."""
    mock_otp_service.verify_code_by_value.return_value = None

    result = await link_service.link_by_otp(
        code="000000", messenger_type="TG", messenger_id="tg_123"
    )

    assert result is None


@pytest.mark.asyncio
async def test_link_by_otp_unknown_messenger(link_service, mock_otp_service):
    """Failure: unknown messenger type."""
    user_id = uuid.uuid4()
    mock_otp_service.verify_code_by_value.return_value = user_id

    result = await link_service.link_by_otp(
        code="123456", messenger_type="UNKNOWN", messenger_id="unk_123"
    )

    assert result is None


@pytest.mark.asyncio
async def test_link_by_otp_user_not_found(link_service, mock_otp_service, mock_session):
    """Failure: user identified by OTP not found in DB."""
    user_id = uuid.uuid4()
    mock_otp_service.verify_code_by_value.return_value = user_id
    mock_session.get.return_value = None

    result = await link_service.link_by_otp(
        code="123456", messenger_type="TG", messenger_id="tg_123"
    )

    assert result is None


@pytest.mark.asyncio
async def test_link_by_invite_code_creates_shadow_user(
    link_service, mock_otp_service, mock_session
):
    """Invite code fallback: creates shadow user and links messenger."""
    company_id = uuid.uuid4()
    mock_otp_service.verify_code_by_value.return_value = None
    mock_otp_service.verify_invite_code.return_value = company_id

    await link_service.link_by_otp(
        code="654321", messenger_type="TG", messenger_id="tg_789"
    )

    # Shadow user was added to session and flushed twice
    assert mock_session.add.called
    added_user = mock_session.add.call_args[0][0]
    assert added_user.email.startswith("invite_")
    assert added_user.email.endswith("@chatflow.local")
    assert added_user.company_id == company_id
    assert added_user.hashed_password != "!"
    assert added_user.hashed_password.startswith("$2b$")
    assert added_user.is_active is True
    assert added_user.telegram_id == "tg_789"
    assert mock_session.flush.await_count == 2


@pytest.mark.asyncio
async def test_link_by_invite_code_invalid_returns_none(link_service, mock_otp_service):
    """Both OTP and invite code invalid → returns None."""
    mock_otp_service.verify_code_by_value.return_value = None
    mock_otp_service.verify_invite_code.return_value = None

    result = await link_service.link_by_otp(
        code="000000", messenger_type="TG", messenger_id="tg_123"
    )

    assert result is None
