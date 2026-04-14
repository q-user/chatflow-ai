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
async def test_register_creates_company_in_db(
    client: AsyncClient, db_session: AsyncSession
):
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
        select(UserTable).where(UserTable.email == "company_test@example.com")  # type: ignore
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
    assert "email" in data
    assert data["id"] is not None
    assert data["company_id"] is not None
    assert "company_name" not in data  # Not part of UserRead


@pytest.mark.asyncio
async def test_register_with_custom_company_name(
    client: AsyncClient, db_session: AsyncSession
):
    """Register with company_name → Company created with specified name."""
    await client.post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "company_name": "My Custom Company",
        },
    )

    result = await db_session.execute(
        select(CompanyTable).where(CompanyTable.name == "My Custom Company")
    )
    company = result.scalar_one_or_none()
    assert company is not None


@pytest.mark.asyncio
async def test_register_with_existing_company(
    client: AsyncClient, db_session: AsyncSession, test_company: CompanyTable
):
    """Register with company_id → no new Company created, uses existing one."""
    initial_count = (
        (await db_session.execute(select(CompanyTable))).scalars().all().__len__()
    )

    await client.post(
        "/auth/register",
        json={
            "email": "existing_co@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "company_id": str(test_company.id),
        },
    )

    result = await db_session.execute(select(CompanyTable))
    companies = result.scalars().all()
    assert len(companies) == initial_count

    result = await db_session.execute(
        select(UserTable).where(UserTable.email == "existing_co@example.com")  # type: ignore
    )
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.company_id == test_company.id


@pytest.mark.asyncio
async def test_register_user_idempotent_company(
    client: AsyncClient, db_session: AsyncSession
):
    """Two users with same company_name share the same Company (created once)."""
    await client.post(
        "/auth/register",
        json={
            "email": "first@shared.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    await client.post(
        "/auth/register",
        json={
            "email": "second@shared.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    result = await db_session.execute(
        select(CompanyTable).where(
            CompanyTable.name.in_(["Company-first", "Company-second"])
        )
    )
    companies = result.scalars().all()
    assert len(companies) == 2


@pytest.mark.asyncio
async def test_cookie_login_returns_204(client: AsyncClient):
    """POST /auth/cookie/login → 204 + Set-Cookie."""
    await client.post(
        "/auth/register",
        json={
            "email": "cookie_login@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    resp = await client.post(
        "/auth/cookie/login",
        data={"username": "cookie_login@example.com", "password": "SecureP@ss123"},
    )
    assert resp.status_code == 204
    assert "set-cookie" in [h.lower() for h in resp.headers.keys()]


@pytest.mark.asyncio
async def test_cookie_login_invalid_credentials(client: AsyncClient):
    """POST /auth/cookie/login with wrong password → 400."""
    await client.post(
        "/auth/register",
        json={
            "email": "cookie_fail@example.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    resp = await client.post(
        "/auth/cookie/login",
        data={"username": "cookie_fail@example.com", "password": "WrongPassword"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(client: AsyncClient):
    """Register same email twice → 400."""
    await client.post(
        "/auth/register",
        json={
            "email": "duplicate@test.com",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    resp = await client.post(
        "/auth/register",
        json={
            "email": "duplicate@test.com",
            "password": "OtherPassword123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )
    assert resp.status_code == 400
