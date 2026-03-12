"""
Audit Log model for security event tracking.
"""

from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEventType(StrEnum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    MISSION_LAUNCHED = "MISSION_LAUNCHED"
    MISSION_DELETED = "MISSION_DELETED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    SHELL_CONNECT = "SHELL_CONNECT"
    EXPLOIT_RECONNECT = "EXPLOIT_RECONNECT"
    API_KEY_CREATED = "API_KEY_CREATED"
    API_KEY_REVOKED = "API_KEY_REVOKED"
    PLAN_CHANGED = "PLAN_CHANGED"
    TOOL_EXECUTED = "TOOL_EXECUTED"


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} event={self.event_type}>"
