"""Server node model for multi-server pool management."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from spectra_common.orm.base import Base

logger = logging.getLogger(__name__)


class ServerNode(Base):
    """Tracks registered server nodes across the infrastructure."""

    __tablename__ = "server_nodes"
    __table_args__ = (
        CheckConstraint("weight >= 0", name="ck_server_nodes_weight_nonneg"),
        CheckConstraint("current_load >= 0", name="ck_server_nodes_current_load_nonneg"),
        CheckConstraint("max_capacity > 0", name="ck_server_nodes_max_capacity_pos"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
    service_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    # SECURITY: api_key is Fernet-encrypted at rest using SECRET_KEY.
    # Use set_api_key() / get_api_key() for transparent encrypt/decrypt.
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
    # SSH deployment fields
    ssh_user: Mapped[str] = mapped_column(String(100), default="ubuntu", server_default="ubuntu", nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, server_default="22", nullable=False)
    ssh_key_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deployed_services: Mapped[dict | None] = mapped_column("deployed_services", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)  # type: ignore[assignment]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )  # type: ignore[assignment]

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
            "ssh_user": self.ssh_user,
            "ssh_port": self.ssh_port,
            "ssh_key_path": self.ssh_key_path,
            "deployed_services": self.deployed_services,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def set_api_key(self, plaintext_key: str | None) -> None:
        """Encrypt and store an API key."""
        if not plaintext_key:
            self.api_key = None
            return
        try:
            from app.auth.encryption import _get_default_secret, encrypt_field

            self.api_key = encrypt_field(plaintext_key, _get_default_secret())
        except (OSError, RuntimeError, ImportError) as e:
            raise RuntimeError(
                f"Cannot store API key: encryption is unavailable ({e}). "
                "Ensure the cryptography package is installed and SECRET_KEY is set."
            ) from e

    def get_api_key(self) -> str | None:
        """Decrypt and return the stored API key."""
        if not self.api_key:
            return None
        try:
            from app.auth.encryption import _get_default_secret, decrypt_field

            return decrypt_field(self.api_key, _get_default_secret())
        except (OSError, RuntimeError, ImportError):
            logger.warning("Failed to decrypt API key for ServerNode %s; returning None", self.id)
            return None

    def __repr__(self) -> str:
        return f"<ServerNode id={self.id} name={self.name!r} type={self.service_type}>"
