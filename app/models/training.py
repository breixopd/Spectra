"""Training dataset and fine-tuning job models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.infrastructure import JSONBType
from spectra_common.orm.base import Base


class TrainingSample(Base):
    """An anonymized training data sample extracted from mission interactions."""

    __tablename__ = "training_samples"

    mission_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("missions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sample_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONBType, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_anonymized: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (Index("ix_training_samples_type_quality", "sample_type", "quality_score"),)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id!r})>"


class FineTuningJob(Base):
    """A fine-tuning job managed through the admin panel."""

    __tablename__ = "fine_tuning_jobs"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    base_model: Mapped[str] = mapped_column(String(200), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sample_types: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_model_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id!r})>"
