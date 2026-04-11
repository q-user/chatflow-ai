from core.domain.user import User
from infrastructure.database.models.user import UserTable
from infrastructure.database.repositories.sqlalchemy_repository import (
    BaseSqlAlchemyRepository,
)


class UserRepository(BaseSqlAlchemyRepository[UserTable, User]):
    """Implementation of user repository using SQLAlchemy."""

    model_class = UserTable
    schema_class = User
