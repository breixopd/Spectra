"""User-level preferences stored in the database."""

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.models.base import Base
from app.models.infrastructure import JSONBType


class UserPreferences(Base):
    """Per-user settings and preferences.

    Uses a single JSONB column for extensibility — new preference keys can be
    added without migrations.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # --- BYOK (Bring Your Own Key) ---
    llm_api_key: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    llm_api_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_api_key: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    embedding_api_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # --- Notification preferences ---
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notify_on_mission_complete: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notify_on_critical_finding: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # --- Default mission preferences ---
    default_scan_mode: Mapped[str] = mapped_column(String(20), default="autonomous", server_default="autonomous")
    default_report_format: Mapped[str] = mapped_column(String(10), default="pdf", server_default="pdf")

    # --- UI preferences ---
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", server_default="UTC")

    # --- Training data sharing ---
    share_training_data: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # --- Extensible JSONB for future preferences ---
    extra: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    __exclude_fields__ = {"llm_api_key", "embedding_api_key"}
