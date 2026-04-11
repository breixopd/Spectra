"""
User model for authentication and authorization.

Stores user credentials and role information for the Spectra platform.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """
    Represents a system user.

    Attributes:
        username: Unique username for login.
        email: User's email address (unique).
        hashed_password: Bcrypt-hashed password.
        is_active: Whether the user account is active.
        is_superuser: Whether the user has admin privileges.
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False, server_default="user")
    plan_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    api_key_prefix: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    login_fail_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="true")
    processing_restricted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")

    __exclude_fields__ = {"hashed_password", "mfa_secret"}

    def __repr__(self) -> str:
        """String representation of the user."""
        return f"<User(id={self.id}, username={self.username}, is_active={self.is_active})>"
