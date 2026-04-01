"""
Target model for storing scan targets.

Provides the central entity that findings and exploits reference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import EntityStatus as TargetStatus
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.exploit import Exploit
    from app.models.finding import Finding


class Target(Base):
    """
    Represents a scan target (host, domain, IP range).

    Attributes:
        address: The actual target value (IP, domain, CIDR).
        description: Optional notes or description.
        status: Current status in the pipeline.
        os: Operating system of the target (if known).
        findings: Related vulnerability findings.
        exploits: Related exploit attempts.
    """

    __tablename__ = "targets"

    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    address: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TargetStatus] = mapped_column(
        SQLEnum(TargetStatus),
        default=TargetStatus.PENDING,
        nullable=False,
        index=True,
    )
    os: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
    findings: Mapped[list[Finding]] = relationship(
        "Finding",
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    exploits: Mapped[list[Exploit]] = relationship(
        "Exploit",
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Target id={self.id} address={self.address!r}>"
