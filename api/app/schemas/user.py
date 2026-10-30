import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator

from app.db.models import Role
from app.schemas.auth import EMAIL_PATTERN, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: Role
    is_active: bool
    must_change_password: bool
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: StrictStr = Field(pattern=EMAIL_PATTERN, max_length=320, examples=["ana@example.com"])
    temporary_password: StrictStr = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description="The user must change it at first login.",
    )
    role: Role = Role.USER

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: StrictBool | None = None


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temporary_password: StrictStr = Field(
        min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH
    )
