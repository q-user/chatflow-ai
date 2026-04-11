"""Integration tests for auth API endpoints (register, login, me)."""


import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable


@pytest.mark.asyncio
async def test_register_returns_201(client: AsyncClient):
    """POST /auth/register → 201 + UserRead schema."""
    resp = await client.post(
        "/auth/register",
        json={
            "email": "new_user@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new_user@example.com"
    assert data["is_active"] is True
    assert data["id"] is not None


@pytest.mark.asyncio
async def test_register_creates_company_in_db(client: AsyncClient, db_session: AsyncSession):
    """Registration without company_id creates a new Company in DB."""
    await client.post(
        "/auth/register",
        json={
            "email": "company_test@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    # Verify company was created
    result = await db_session.execute(
        select(CompanyTable).where(CompanyTable.name == "Company-company_test")
    )
    company = result.scalar_one_or_none()
    assert company is not None

    # Verify user is linked to this company
    result = await db_session.execute(
        select(UserTable).where(UserTable.email == "company_test@example.com")
    )
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.company_id == company.id


@pytest.mark.asyncio
async def test_login_returns_200(client: AsyncClient):
    """POST /auth/login → 200 + access_token."""
    # Register first
    await client.post(
        "/auth/register",
        json={
            "email": "login_test@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    resp = await client.post(
        "/auth/login",
        data={"username": "login_test@example.com", "password": "SecureP@ss123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """POST /auth/login with wrong password → 400."""
    # Register first
    await client.post(
        "/auth/register",
        json={
            "email": "wrong_pass@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    resp = await client.post(
        "/auth/login",
        data={"username": "wrong_pass@example.com", "password": "WrongPassword123"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    """GET /users/me without JWT → 401."""
    resp = await client.get("/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user(auth_client: AsyncClient):
    """GET /users/me with valid JWT → 200 + UserRead."""
    resp = await auth_client.get("/users/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "auth_test@example.com"
    assert data["id"] is not None
    assert data["company_id"] is not None
    assert "company_name" not in data  # Not part of UserRead
