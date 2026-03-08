"""
User model for authentication and authorization.

Stores user credentials and role information for the Spectra platform.
"""

from sqlalchemy import Boolean, String
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
    role: Mapped[str] = mapped_column(
        String(20), default="operator", nullable=False, server_default="operator"
    )

    __exclude_fields__ = {"hashed_password"}

    def __repr__(self) -> str:
        """String representation of the user."""
        return f"<User(id={self.id}, username={self.username}, is_active={self.is_active})>"
