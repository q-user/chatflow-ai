"""Integration tests for OTP API endpoints (generate, verify)."""

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
    # Generate OTP (user_id resolved via reverse lookup)
    otp_resp = await auth_client.post("/auth/otp")
    assert otp_resp.status_code == 201
    code = otp_resp.json()["code"]

    # Verify OTP with bot API key (no user_id needed)
    verify_resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "code": code,
            "messenger_id": "telegram_12345",
            "messenger_type": "TG",
        },
        headers=bot_api_headers,
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "ok"

    # Verify telegram_id was linked to the user who generated the OTP
    me_resp = await auth_client.get("/users/me")
    user_id = me_resp.json()["id"]
    result = await db_session.execute(select(UserTable).where(UserTable.id == user_id))  # type: ignore
    user = result.scalar_one()
    assert user.telegram_id == "telegram_12345"


@pytest.mark.asyncio
async def test_verify_otp_invalid_code(
    auth_client: AsyncClient,
    bot_api_headers: dict[str, str],
):
    """POST /auth/otp/verify with wrong code → 404."""
    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "code": "000000",  # Wrong code — never generated
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
    """POST /auth/otp/verify with invalid messenger_type → 422."""
    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "code": "123456",
            "messenger_id": "wa_12345",
            "messenger_type": "WA",  # Invalid!
        },
        headers=bot_api_headers,
    )
    assert resp.status_code == 422  # Pydantic validation error (Literal["TG", "YM"])


@pytest.mark.asyncio
async def test_verify_otp_code_already_consumed(
    auth_client: AsyncClient,
    bot_api_headers: dict[str, str],
):
    """POST /auth/otp/verify with already-used code → 404."""
    # Generate OTP
    otp_resp = await auth_client.post("/auth/otp")
    code = otp_resp.json()["code"]

    # First verification — success
    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "code": code,
            "messenger_id": "telegram_first",
            "messenger_type": "TG",
        },
        headers=bot_api_headers,
    )
    assert resp.status_code == 200

    # Second verification with same code → 404 (code consumed)
    resp = await auth_client.post(
        "/auth/otp/verify",
        json={
            "code": code,
            "messenger_id": "telegram_second",
            "messenger_type": "TG",
        },
        headers=bot_api_headers,
    )
    assert resp.status_code == 404
