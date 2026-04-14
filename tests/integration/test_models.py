"""Integration tests for database models, constraints, and relationships."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable


@pytest.mark.asyncio
async def test_create_company(db_session: AsyncSession):
    """CompanyTable can be created and returns a UUID."""
    company = CompanyTable(name="Test Company")
    db_session.add(company)
    await db_session.flush()

    assert company.id is not None
    assert isinstance(company.id, uuid.UUID)

    # Verify it's in the DB
    result = await db_session.execute(
        select(CompanyTable).where(CompanyTable.id == company.id)
    )
    saved = result.scalar_one()
    assert saved.name == "Test Company"


@pytest.mark.asyncio
async def test_user_requires_company_id(db_session: AsyncSession):
    """User cannot be created without company_id (NOT NULL constraint)."""
    user = UserTable(
        email="no_company@example.com",
        hashed_password="pass",
        company_id=None,  # type: ignore[arg-type]
    )
    db_session.add(user)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_user_telegram_id_unique(
    db_session: AsyncSession, test_company: CompanyTable
):
    """Two users cannot have the same telegram_id (UNIQUE constraint)."""
    user1 = UserTable(
        email="u1@example.com",
        hashed_password="pass",
        company_id=test_company.id,
        telegram_id="123456789",
    )
    user2 = UserTable(
        email="u2@example.com",
        hashed_password="pass",
        company_id=test_company.id,
        telegram_id="123456789",  # Duplicate!
    )
    db_session.add_all([user1, user2])

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_user_yandex_id_unique(
    db_session: AsyncSession, test_company: CompanyTable
):
    """Two users cannot have the same yandex_id (UNIQUE constraint)."""
    user1 = UserTable(
        email="u1@example.com",
        hashed_password="pass",
        company_id=test_company.id,
        yandex_id="yandex_123",
    )
    user2 = UserTable(
        email="u2@example.com",
        hashed_password="pass",
        company_id=test_company.id,
        yandex_id="yandex_123",  # Duplicate!
    )
    db_session.add_all([user1, user2])

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_bot_instance_fk_company(db_session: AsyncSession):
    """BotInstance cannot be created with non-existent company_id (FK constraint).

    On SQLite, PRAGMA foreign_keys must be enabled.
    On PostgreSQL, FK is enforced automatically.
    """
    # Check if we're on SQLite — only then enable PRAGMA
    dialect_name = db_session.get_bind().dialect.name
    if dialect_name == "sqlite":
        await db_session.execute(text("PRAGMA foreign_keys = ON"))

    fake_company_id = uuid.uuid4()
    bot = BotInstanceTable(
        company_id=fake_company_id,
        messenger_type="TG",
        token="bot_token_123",
    )
    db_session.add(bot)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_bot_instance_messenger_type_check(
    db_session: AsyncSession, test_company: CompanyTable
):
    """BotInstance rejects invalid messenger_type (CheckConstraint)."""
    bot = BotInstanceTable(
        company_id=test_company.id,
        messenger_type="WA",  # Invalid! Only TG/YM allowed
        token="bot_token_123",
    )
    db_session.add(bot)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_company_users_relationship(db_session: AsyncSession):
    """Company.users relationship returns associated users."""
    company = CompanyTable(name="Company With Users")
    db_session.add(company)
    await db_session.flush()

    user1 = UserTable(email="u1@co.com", hashed_password="pass", company_id=company.id)
    user2 = UserTable(email="u2@co.com", hashed_password="pass", company_id=company.id)
    db_session.add_all([user1, user2])
    await db_session.flush()

    # Use explicit query with selectinload instead of lazy loading
    result = await db_session.execute(
        select(CompanyTable)
        .where(CompanyTable.id == company.id)
        .options(selectinload(CompanyTable.users))
    )
    loaded_company = result.scalar_one()
    assert len(loaded_company.users) == 2
    emails = {u.email for u in loaded_company.users}
    assert emails == {"u1@co.com", "u2@co.com"}


@pytest.mark.asyncio
async def test_company_bots_relationship(db_session: AsyncSession):
    """Company.bots relationship returns associated bot instances."""
    company = CompanyTable(name="Company With Bots")
    db_session.add(company)
    await db_session.flush()

    bot1 = BotInstanceTable(
        company_id=company.id, messenger_type="TG", token="tg_token"
    )
    bot2 = BotInstanceTable(
        company_id=company.id, messenger_type="YM", token="ym_token"
    )
    db_session.add_all([bot1, bot2])
    await db_session.flush()

    # Use explicit query with selectinload instead of lazy loading
    result = await db_session.execute(
        select(CompanyTable)
        .where(CompanyTable.id == company.id)
        .options(selectinload(CompanyTable.bots))
    )
    loaded_company = result.scalar_one()
    assert len(loaded_company.bots) == 2
    types = {b.messenger_type for b in loaded_company.bots}
    assert types == {"TG", "YM"}


@pytest.mark.asyncio
async def test_user_company_relationship(
    db_session: AsyncSession, test_company: CompanyTable
):
    """User.company relationship returns the associated company."""
    user = UserTable(
        email="u@co.com",
        hashed_password="pass",
        company_id=test_company.id,
    )
    db_session.add(user)
    await db_session.flush()

    result = await db_session.execute(
        select(UserTable)
        .where(UserTable.id == user.id)  # type: ignore
        .options(selectinload(UserTable.company))
    )
    loaded_user = result.scalar_one()
    assert loaded_user.company is not None
    assert loaded_user.company.id == test_company.id
    assert loaded_user.company.name == "Test Company"


@pytest.mark.asyncio
async def test_bot_instance_valid_messenger_types(
    db_session: AsyncSession, test_company: CompanyTable
):
    """BotInstance accepts both TG and YM messenger types."""
    tg_bot = BotInstanceTable(
        company_id=test_company.id, messenger_type="TG", token="tg"
    )
    ym_bot = BotInstanceTable(
        company_id=test_company.id, messenger_type="YM", token="ym"
    )
    db_session.add_all([tg_bot, ym_bot])
    await db_session.flush()

    assert tg_bot.id is not None
    assert ym_bot.id is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("module_type", ["finance", "hr"])
async def test_bot_instance_module_type(
    db_session: AsyncSession, test_company: CompanyTable, module_type: str
):
    """BotInstance accepts custom module_type."""
    bot = BotInstanceTable(
        company_id=test_company.id,
        messenger_type="TG",
        token="tg",
        module_type=module_type,
    )
    db_session.add(bot)
    await db_session.flush()

    assert bot.module_type == module_type


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"system_prompt": "You are a bot"}, None])
async def test_bot_instance_config(
    db_session: AsyncSession, test_company: CompanyTable, config: dict | None
):
    """BotInstance accepts dict config or None."""
    bot = BotInstanceTable(
        company_id=test_company.id,
        messenger_type="TG",
        token="tg",
        config=config,
    )
    db_session.add(bot)
    await db_session.flush()

    assert bot.config == config


@pytest.mark.asyncio
async def test_user_default_status_fields(
    db_session: AsyncSession, test_company: CompanyTable
):
    """User has default values for is_superuser, is_verified, is_active."""
    user = UserTable(
        email="defaults@co.com",
        hashed_password="pass",
        company_id=test_company.id,
    )
    db_session.add(user)
    await db_session.flush()

    assert user.is_active is True
    assert user.is_superuser is False
    assert user.is_verified is False
