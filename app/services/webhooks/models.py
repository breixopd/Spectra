"""SQLAlchemy model for webhook registrations."""

from __future__ import annotations

import logging

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.infrastructure import JSONBType

logger = logging.getLogger(__name__)


class Webhook(Base):
    """A registered webhook endpoint for event delivery."""

    __tablename__ = "webhooks"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    events: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<Webhook(id={self.id}, user_id={self.user_id}, url={self.url!r})>"
