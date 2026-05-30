"""
Rules of Engagement (RoE) model for structured mission constraints.

Provides enforceable constraints for missions including authorized targets,
prohibited actions, scan intensity limits, and data exfiltration controls.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from spectra_persistence.orm.base import Base


def _utc_now() -> datetime:
    return datetime.utcnow()


class RulesOfEngagement(Base):
    """
    Structured Rules of Engagement for a mission.

    Provides enforceable constraints that the mission engine checks before
    executing actions. Supplements the existing prose rules_of_engagement field.

    Attributes:
        mission_id: Foreign key to the associated mission (unique)
        authorized_targets: List of allowed target addresses (IPs, CIDRs, domains)
        excluded_targets: List of explicitly prohibited targets
        authorized_actions: List of allowed action types
        prohibited_actions: List of explicitly prohibited action types
        max_scan_intensity: Scan intensity level (passive/light/normal/aggressive)
        data_exfiltration_allowed: Whether data exfiltration is permitted
        max_exfiltration_bytes: Maximum bytes allowed for exfiltration
        allow_persistence: Whether persistence mechanisms are allowed
        notification_email: Optional email for RoE violation notifications
        operator_signoff_required: Whether operator signoff is required for execution
        additional_constraints: Free-form prose for additional constraints
    """

    __tablename__ = "rules_of_engagement"
    __table_args__ = (
        Index("ix_roe_mission_id", "mission_id"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    mission_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("missions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # Structured constraints
    authorized_targets: Mapped[list | None] = mapped_column(
        JSON, nullable=True, default=list
    )
    excluded_targets: Mapped[list | None] = mapped_column(
        JSON, nullable=True, default=list
    )
    authorized_actions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, default=list
    )
    prohibited_actions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, default=list
    )
    max_scan_intensity: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )
    data_exfiltration_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    max_exfiltration_bytes: Mapped[int | None] = mapped_column(
        nullable=True
    )
    allow_persistence: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    notification_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    operator_signoff_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    additional_constraints: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<RulesOfEngagement(mission_id={self.mission_id}, intensity={self.max_scan_intensity})>"
