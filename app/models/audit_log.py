"""
Audit Log model for security event tracking.
"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.compat import StrEnum


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
    REGISTRATION = "REGISTRATION"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_DISABLED = "MFA_DISABLED"
    PASSWORD_RESET = "PASSWORD_RESET"
    ACCOUNT_DELETED = "ACCOUNT_DELETED"
    API_KEY_CREATED = "API_KEY_CREATED"
    API_KEY_REVOKED = "API_KEY_REVOKED"
    BYOK_CHANGED = "BYOK_CHANGED"
    USER_STATUS_CHANGED = "USER_STATUS_CHANGED"
    PLAN_CHANGED = "PLAN_CHANGED"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    MISSION_STATUS_CHANGED = "MISSION_STATUS_CHANGED"
    ROLLBACK_PERFORMED = "ROLLBACK_PERFORMED"
    USER_CREATED = "USER_CREATED"
    USER_DELETED = "USER_DELETED"
    TARGET_CREATED = "TARGET_CREATED"
    TARGET_DELETED = "TARGET_DELETED"
    FINDING_CREATED = "FINDING_CREATED"
    FINDING_UPDATED = "FINDING_UPDATED"
    FINDING_DELETED = "FINDING_DELETED"
    EXPLOIT_EXECUTED = "EXPLOIT_EXECUTED"
    TOOL_INSTALLED = "TOOL_INSTALLED"
    TOOL_REMOVED = "TOOL_REMOVED"
    TOOL_ENABLED = "TOOL_ENABLED"
    TOOL_DISABLED = "TOOL_DISABLED"
    TOOL_EXECUTED = "TOOL_EXECUTED"
    DATA_CLEARED = "DATA_CLEARED"
    CACHE_CLEARED = "CACHE_CLEARED"
    BACKUP_CREATED = "BACKUP_CREATED"
    BACKUP_RESTORED = "BACKUP_RESTORED"
    DATA_EXPORTED = "DATA_EXPORTED"
    DATA_SOURCES_UPDATED = "DATA_SOURCES_UPDATED"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    integrity_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} event={self.event_type}>"
