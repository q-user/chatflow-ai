from typing import Any, Literal

from pydantic import UUID4, BaseModel, ConfigDict, EmailStr

from fastapi_users.schemas import BaseUserCreate, BaseUserUpdate


class UserRead(BaseUserCreate):
    """Schema for reading user data (GET responses)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    company_id: UUID4
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False
    telegram_id: str | None = None
    yandex_id: str | None = None


class UserCreate(BaseUserCreate):
    """Schema for user registration with optional company creation.

    If company_id is not provided, a new company will be created
    using company_name (or auto-generated from email).
    """

    company_id: UUID4 | None = None
    company_name: str | None = None

    def create_update_dict(self) -> dict[str, Any]:
        """Return dict for DB insert — includes company_id, excludes company_name."""
        result = super().create_update_dict()
        result.pop("company_name", None)
        result["company_id"] = self.company_id
        return result

    def create_update_dict_superuser(self) -> dict[str, Any]:
        """Return dict for superuser insert — includes company_id, excludes company_name."""
        result = super().create_update_dict_superuser()
        result.pop("company_name", None)
        result["company_id"] = self.company_id
        return result


class UserUpdate(BaseUserUpdate):
    """Schema for updating existing user."""

    company_id: UUID4 | None = None
    telegram_id: str | None = None
    yandex_id: str | None = None


class OTPGenerateResponse(BaseModel):
    """Response after OTP generation."""

    code: str
    message: str = "OTP code generated"


class OTPVerifyRequest(BaseModel):
    """Request body for OTP verification (bot API key authenticated).

    user_id is intentionally omitted — it is resolved via reverse OTP lookup
    from the code value. The bot client should not need to know user_id.
    """

    code: str
    messenger_id: str
    messenger_type: Literal["TG", "YM"]
