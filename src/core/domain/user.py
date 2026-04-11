from pydantic import UUID4, BaseModel, ConfigDict, EmailStr


class User(BaseModel):
    """Domain entity representing a system user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID4 | None = None
    email: EmailStr
    hashed_password: str
    is_active: bool = True
