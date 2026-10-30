from pydantic import BaseModel, ConfigDict, Field, StrictStr

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: StrictStr = Field(max_length=320, examples=["admin@example.com"])
    password: StrictStr = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: StrictStr = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: StrictStr = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: StrictStr = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"At least {MIN_PASSWORD_LENGTH} characters; must differ from the current one.",
    )


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    must_change_password: bool = Field(
        description="When true, only /auth/me and /auth/change-password are usable."
    )
