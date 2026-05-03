"""
Finding model for storing vulnerability findings.

Represents security findings discovered during assessments.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spectra_common.orm.base import Base
from spectra_platform.mission.core.enums import Severity

if TYPE_CHECKING:
    from spectra_platform.models.target import Target


class FindingStatus(StrEnum):
    """Verification status of a finding."""

    POTENTIAL = "potential"  # AI detected, not verified
    VERIFIED = "verified"  # Consensus reached (K-threshold)
    EXPLOITED = "exploited"  # Successfully exploited
    FALSE_POSITIVE = "false_positive"
    DISMISSED = "dismissed"
    RETEST_PENDING = "retest_pending"


class Finding(Base):
    """
    Represents a security finding (vulnerability, misconfiguration).

    Attributes:
        target_id: Foreign key to the Target.
        title: Short description of the finding.
        description: Detailed explanation.
        severity: CVSS-based severity level.
        status: Verification status.
        cvss_score: Optional CVSS v3.1 score.
        cve_id: Optional CVE identifier.
        tool_source: The tool that discovered this finding.
        evidence: JSON blob with raw evidence data.
        target: Reference to the parent Target.
    """

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_user_id_severity", "user_id", "severity"),
        Index("ix_findings_cve_id", "cve_id"),
        CheckConstraint(
            "cvss_score IS NULL OR (cvss_score >= 0 AND cvss_score <= 10)",
            name="ck_findings_cvss_range",
        ),
    )

    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[Severity] = mapped_column(
        SQLEnum(Severity),
        default=Severity.INFO,
        nullable=False,
        index=True,
    )
    status: Mapped[FindingStatus] = mapped_column(
        SQLEnum(FindingStatus),
        default=FindingStatus.POTENTIAL,
        nullable=False,
        index=True,
    )
    cvss_score: Mapped[float | None] = mapped_column(nullable=True)
    cve_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    tool_source: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationship
    target: Mapped[Target] = relationship("Target", back_populates="findings", lazy="select")

    def __repr__(self) -> str:
        return f"<Finding id={self.id} title={self.title!r} severity={self.severity}>"
