import pytest
from core.domain.user import User
from infrastructure.database.repositories.user_repository import UserRepository


@pytest.mark.asyncio
async def test_user_repository_add_and_get(db_session, test_company):
    """
    Проверяем полный цикл:
    Domain User -> UserRepository -> SQLAlchemy -> SQLite -> Domain User
    """
    # 1. Инициализируем репозиторий с тестовой сессией
    repo = UserRepository(db_session)

    # 2. Создаем чистую доменную сущность с привязкой к компании
    new_user = User(
        company_id=test_company.id,
        email="test@example.com",
        hashed_password="extremely_safe_password",
        is_active=True,
    )

    # 3. Сохраняем в базу через репозиторий
    saved_user = await repo.add(new_user)

    # Проверяем, что базе был присвоен UUID
    assert saved_user.id is not None
    assert saved_user.email == "test@example.com"

    # 4. Пробуем получить этого же пользователя по ID
    fetched_user = await repo.get_by_id(saved_user.id)

    assert fetched_user is not None
    assert fetched_user.id == saved_user.id
    assert fetched_user.email == "test@example.com"
    # Проверяем, что это именно наш доменный объект, а не модель SQLAlchemy
    assert isinstance(fetched_user, User)


@pytest.mark.asyncio
async def test_user_repository_list(db_session, test_company):
    repo = UserRepository(db_session)

    # Count users before adding
    users_before = await repo.list()
    count_before = len(users_before)

    # Добавляем двух пользователей в компанию
    await repo.add(
        User(company_id=test_company.id, email="u1@test.com", hashed_password="1")
    )
    await repo.add(
        User(company_id=test_company.id, email="u2@test.com", hashed_password="2")
    )

    users = await repo.list()
    assert len(users) == count_before + 2
    assert users[-2].email in ["u1@test.com", "u2@test.com"]
