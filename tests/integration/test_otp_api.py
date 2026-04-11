"""Integration tests for OTP API endpoints (generate, verify)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models.user import UserTable


@pytest.mark.asyncio
async def test_generate_otp_requires_auth(client: AsyncClient):
    """POST /auth/otp without JWT → 401."""
    resp = await client.post("/auth/otp")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_generate_otp_returns_code(auth_client: AsyncClient):
    """POST /auth/otp with JWT → 201 + {code: "123456"}."""
    resp = await auth_client.post("/auth/otp")
    assert resp.status_code == 201
    data = resp.json()
    assert "code" in data
    assert len(data["code"]) == 6
    assert data["code"].isdigit()


@pytest.mark.asyncio
async def test_generate_otp_rate_limit(auth_client: AsyncClient):
    """Two POST /auth/otp within 60s → 429 on second."""
    resp = await auth_client.post("/auth/otp")
    assert resp.status_code == 201

    resp = await auth_client.post("/auth/otp")
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_verify_otp_requires_api_key(auth_client: AsyncClient):
    """POST /auth/otp/verify without X-API-Key → 403."""
    # First generate OTP
    await auth_client.post("/auth/otp")

    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "user_id": str(uuid.uuid4()),
            "code": "123456",
            "messenger_id": "test_123",
            "messenger_type": "TG",
        },
        headers={"X-API-Key": ""},  # Empty key
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_verify_otp_wrong_api_key(auth_client: AsyncClient):
    """POST /auth/otp/verify with wrong X-API-Key → 403."""
    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "user_id": str(uuid.uuid4()),
            "code": "123456",
            "messenger_id": "test_123",
            "messenger_type": "TG",
        },
        headers={"X-API-Key": "wrong_key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_verify_otp_success(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    bot_api_headers: dict[str, str],
):
    """Full OTP flow: generate → verify → telegram_id saved in DB."""
    # Get current user ID
    me_resp = await auth_client.get("/users/me")
    user_id = me_resp.json()["id"]

    # Generate OTP
    otp_resp = await auth_client.post("/auth/otp")
    assert otp_resp.status_code == 201
    code = otp_resp.json()["code"]

    # Verify OTP with bot API key
    verify_resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "user_id": user_id,
            "code": code,
            "messenger_id": "telegram_12345",
            "messenger_type": "TG",
        },
        headers=bot_api_headers,
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "ok"

    # Verify telegram_id in DB
    result = await db_session.execute(
        select(UserTable).where(UserTable.id == user_id)
    )
    user = result.scalar_one()
    assert user.telegram_id == "telegram_12345"


@pytest.mark.asyncio
async def test_verify_otp_invalid_code(
    auth_client: AsyncClient,
    bot_api_headers: dict[str, str],
):
    """POST /auth/otp/verify with wrong code → 404."""
    # Get current user ID
    me_resp = await auth_client.get("/users/me")
    user_id = me_resp.json()["id"]

    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "user_id": user_id,
            "code": "000000",  # Wrong code
            "messenger_id": "telegram_12345",
            "messenger_type": "TG",
        },
        headers=bot_api_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_verify_otp_unknown_messenger_type(
    auth_client: AsyncClient,
    bot_api_headers: dict[str, str],
):
    """POST /auth/otp/verify with invalid messenger_type → 400."""
    me_resp = await auth_client.get("/users/me")
    user_id = me_resp.json()["id"]

    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "user_id": user_id,
            "code": "123456",
            "messenger_id": "wa_12345",
            "messenger_type": "WA",  # Invalid!
        },
        headers=bot_api_headers,
    )
    assert resp.status_code == 422  # Pydantic validation error (Literal["TG", "YM"])


@pytest.mark.asyncio
async def test_verify_otp_user_not_found(
    auth_client: AsyncClient,
    bot_api_headers: dict[str, str],
):
    """POST /auth/otp/verify with non-existent user_id → 404."""
    # Generate OTP first (to have a valid code)
    await auth_client.post("/auth/otp")

    # But verify with wrong user_id
    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "user_id": str(uuid.uuid4()),  # Non-existent user
            "code": "123456",
            "messenger_id": "telegram_12345",
            "messenger_type": "TG",
        },
        headers=bot_api_headers,
    )
    # 404 because user not found (or code doesn't match this user)
    assert resp.status_code == 404
