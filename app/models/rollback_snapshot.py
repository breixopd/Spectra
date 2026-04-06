"""
Rollback Snapshot — stores before-state for reversible admin/operator actions.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RollbackSnapshot(Base):
    __tablename__ = "rollback_snapshots"

    actor_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "user", "mission"
    target_entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # human-readable label
    before_state: Mapped[str] = mapped_column(Text, nullable=False)  # JSON snapshot of before
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rolled_back_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<RollbackSnapshot id={self.id} entity={self.target_entity_type}:{self.target_entity_id}>"
