"""Authentication and user schemas."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

# UserBase and UserCreate live in core to avoid circular imports.
# Re-exported here for backward compatibility.
from app.core.schemas import UserBase, UserCreate  # noqa: F401


class Token(BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Decoded JWT token data."""

    username: str | None = None


class UserResponse(UserBase):
    """Schema for user response."""

    id: str
    is_active: bool
    is_superuser: bool

    model_config = ConfigDict(from_attributes=True)


class ForgotPasswordRequest(BaseModel):
    """Schema for password reset request."""

    email: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        description="Email address associated with the account",
    )


class ResetPasswordRequest(BaseModel):
    """Schema for resetting password with a token."""

    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v
