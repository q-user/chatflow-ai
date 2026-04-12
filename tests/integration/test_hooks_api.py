"""Integration tests for webhook API endpoint.

Tests POST /api/v1/hooks/{messenger_type}/{bot_uuid} end-to-end
via the hooks_client fixture (wired to mock adapter).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable


# ──────────────────────────────────────────────
# Basic webhook tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hooks_returns_200_for_valid_webhook(
    hooks_client: AsyncClient,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
):
    """Valid webhook → 200 OK."""
    payload = {
        "message": {
            "chat": {"id": 123456},
            "from": {"id": 999888777},
            "text": "hello",
        }
    }

    resp = await hooks_client.post(
        f"/api/v1/hooks/TG/{test_bot_instance.id}",
        json=payload,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # verify mock adapter was called
    mock_adapter.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_hooks_returns_200_even_for_invalid_bot(
    hooks_client: AsyncClient,
    mock_adapter,
):
    """Non-existent bot → 200 (Telegram compat — must respond within 60s)."""
    fake_bot_id = uuid.uuid4()
    payload = {
        "message": {
            "chat": {"id": 123456},
            "from": {"id": 999888777},
            "text": "hello",
        }
    }

    resp = await hooks_client.post(
        f"/api/v1/hooks/TG/{fake_bot_id}",
        json=payload,
    )
    assert resp.status_code == 200


# ──────────────────────────────────────────────
# Full OTP flow via webhook
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hooks_full_otp_flow(
    hooks_client: AsyncClient,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
    otp_service,
):
    """Register → generate OTP → webhook with OTP → linked."""
    # 1. Create user in DB
    user = UserTable(
        email=f"otp_webhook_user_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="pass",
        company_id=test_company.id,
    )
    db_session.add(user)
    await db_session.flush()

    # 2. Generate OTP
    code = await otp_service.generate_code(user.id)

    # 3. Send OTP via webhook (unknown messenger_user_id)
    messenger_id = f"777666555_{uuid.uuid4().hex[:8]}"
    payload = {
        "message": {
            "chat": {"id": messenger_id},
            "from": {"id": messenger_id},
            "text": code,
        }
    }

    resp = await hooks_client.post(
        f"/api/v1/hooks/TG/{test_bot_instance.id}",
        json=payload,
    )
    assert resp.status_code == 200

    # 4. Verify messenger was linked in DB
    await db_session.refresh(user)
    assert user.telegram_id == messenger_id

    # 5. Verify success message was sent
    call_args = mock_adapter.send_text.call_args
    assert "привязан" in call_args[0][1].lower()


# ──────────────────────────────────────────────
# Full session flow via webhook
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hooks_session_flow(
    hooks_client: AsyncClient,
    test_bot_instance: BotInstanceTable,
    mock_adapter,
    db_session: AsyncSession,
    test_company: CompanyTable,
):
    """Known user: /new → accumulate text → /compile → snapshot returned."""
    telegram_id = f"111222333_{uuid.uuid4().hex[:8]}"
    user = UserTable(
        email=f"session_flow_user_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="pass",
        company_id=test_company.id,
        telegram_id=telegram_id,
    )
    db_session.add(user)
    await db_session.flush()

    # 1. Send /new
    resp = await hooks_client.post(
        f"/api/v1/hooks/TG/{test_bot_instance.id}",
        json={
            "message": {
                "chat": {"id": telegram_id},
                "from": {"id": telegram_id},
                "text": "/new",
            }
        },
    )
    assert resp.status_code == 200
    assert "сессия начата" in mock_adapter.send_text.call_args[0][1].lower()
    mock_adapter.send_text.reset_mock()

    # 2. Accumulate some data
    resp = await hooks_client.post(
        f"/api/v1/hooks/TG/{test_bot_instance.id}",
        json={
            "message": {
                "chat": {"id": telegram_id},
                "from": {"id": telegram_id},
                "text": "data item 1",
            }
        },
    )
    assert resp.status_code == 200
    assert "принято" in mock_adapter.send_text.call_args[0][1].lower()
    mock_adapter.send_text.reset_mock()

    # 3. Compile
    resp = await hooks_client.post(
        f"/api/v1/hooks/TG/{test_bot_instance.id}",
        json={
            "message": {
                "chat": {"id": telegram_id},
                "from": {"id": telegram_id},
                "text": "/compile",
            }
        },
    )
    assert resp.status_code == 200
    assert "принято" in mock_adapter.send_text.call_args[0][1].lower()
