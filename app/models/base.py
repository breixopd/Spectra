"""
SQLAlchemy Base Model.

All database models should inherit from this Base class.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.

    Provides:
        - id: UUID primary key
        - created_at: Timestamp of creation
        - updated_at: Timestamp of last update
    """

    # Common columns for all models
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
        nullable=False,
    )

    __exclude_fields__: set[str] = set()
    __include_fields__: set[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert model to dictionary."""
        data = {}
        for c in self.__table__.columns:
            if self.__include_fields__ is not None and c.name not in self.__include_fields__:
                continue
            if c.name in self.__exclude_fields__:
                continue
            data[c.name] = getattr(self, c.name)
        return data
