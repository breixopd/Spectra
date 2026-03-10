"""Server node model for multi-server pool management."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class ServerNode(Base):
    """Tracks registered server nodes across the infrastructure."""
    __tablename__ = "server_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
    service_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_capacity: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    current_load: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)  # type: ignore[assignment]
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_type": self.service_type,
            "name": self.name,
            "url": self.url,
            "is_active": self.is_active,
            "is_primary": self.is_primary,
            "weight": self.weight,
            "max_capacity": self.max_capacity,
            "current_load": self.current_load,
            "health_status": self.health_status,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "last_error": self.last_error,
            "metadata": self.metadata_,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
