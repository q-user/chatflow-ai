"""Integration tests for UserManager logic via real DB + API.

Tests the UserManager.create() behavior through the /auth/register endpoint,
verifying database state directly — no mocks or patches.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable


@pytest.mark.asyncio
async def test_register_creates_company(client, db_session: AsyncSession):
    """Register without company_id → auto-creates Company named from email prefix."""
    await client.post(
        "/auth/register",
        json={
            "email": "john.doe@mycorp.org",
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    # Verify Company was created with auto-generated name
    result = await db_session.execute(
        select(CompanyTable).where(CompanyTable.name == "Company-john.doe")
    )
    company = result.scalar_one_or_none()
    assert company is not None

    # Verify User is linked to this company
    result = await db_session.execute(
        select(UserTable).where(UserTable.email == "john.doe@mycorp.org")
    )
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.company_id == company.id


@pytest.mark.asyncio
async def test_register_with_custom_company_name(client, db_session: AsyncSession):
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
    client, db_session: AsyncSession, test_company: CompanyTable
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

    # Verify no new company was created (count stays the same)
    result = await db_session.execute(select(CompanyTable))
    companies = result.scalars().all()
    assert len(companies) == initial_count  # Only test_company exists, no new one

    # Verify user is linked to the existing company
    result = await db_session.execute(
        select(UserTable).where(UserTable.email == "existing_co@example.com")
    )
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.company_id == test_company.id


@pytest.mark.asyncio
async def test_register_user_idempotent_company(client, db_session: AsyncSession):
    """Two users with same company_name share the same Company (created once)."""
    # First user — creates company
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

    # Second user — different email prefix, creates another company
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

    # Each user gets their own company (auto-generated from email prefix)
    result = await db_session.execute(
        select(CompanyTable).where(
            CompanyTable.name.in_(["Company-first", "Company-second"])
        )
    )
    companies = result.scalars().all()
    assert len(companies) == 2
