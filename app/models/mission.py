"""
Mission model for storing mission execution history.

Tracks security assessment missions, their status, logs, and results.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import MissionStatus
from app.models.base import Base


class Mission(Base):
    """
    Represents a security assessment mission execution.

    Attributes:
        target: The target address (IP, domain, or URL).
        directive: The user's high-level goal for the assessment.
        status: Current status of the mission.
        logs: List of log entries from mission execution.
        summary: Final mission summary and report data.
    """

    __tablename__ = "missions"
    __table_args__ = (Index("ix_missions_user_id_status", "user_id", "status"),)

    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    directive: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=MissionStatus.CREATED.value,
        nullable=False,
        index=True,
    )
    logs: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    attack_surface: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    checkpoint_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    resume: Mapped[bool] = mapped_column(default=False, nullable=False)
    vpn_config: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)

    def __repr__(self) -> str:
        """String representation of the mission."""
        return f"<Mission(id={self.id}, target={self.target}, status={self.status})>"
