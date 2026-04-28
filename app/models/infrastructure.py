import json
from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, TypeDecorator, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import String as SAString

from app.models.base import Base


class InfrastructureBase(DeclarativeBase):
    """Base for infrastructure tables that don't share the standard UUID/timestamp columns.

    Shares metadata with ``Base`` so Alembic autogenerate sees all tables
    through a single ``target_metadata = Base.metadata``.
    """

    metadata = Base.metadata


class JSONBType(TypeDecorator):
    """Fallback JSONB type for SQLite testing."""

    impl = SAString
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(SAString())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return json.loads(value)


class SystemCache(InfrastructureBase):
    """
    PostgreSQL-backed key-value cache.
    """

    __tablename__ = "system_cache"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONBType, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(key={self.key!r})>"


class JobQueue(InfrastructureBase):
    """
    PostgreSQL-backed job queue.
    Replaces ARQ for background task execution.
    """

    __tablename__ = "job_queue"
    __table_args__ = (
        Index("ix_job_queue_status_queue", "status", "queue_name"),
        CheckConstraint("priority >= 1 AND priority <= 10", name="ck_job_queue_priority_range"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    queue_name: Mapped[str] = mapped_column(String, nullable=False, default="default", index=True)
    function: Mapped[str] = mapped_column(String, nullable=False)
    args: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    kwargs: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", index=True
    )  # queued, in_progress, completed, failed
    result: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONBType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in seconds
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5, index=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id!r})>"


class Sandbox(InfrastructureBase):
    """Tracks per-mission ephemeral sandbox containers."""

    __tablename__ = "sandboxes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    container_id: Mapped[str] = mapped_column(String, nullable=False)
    container_name: Mapped[str] = mapped_column(String, nullable=False)
    queue_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="creating")
    image: Mapped[str] = mapped_column(String, nullable=False)
    resource_tier: Mapped[str | None] = mapped_column(String, nullable=True, default="medium")
    network_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True, index=True)
    escalated: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id!r})>"


class SystemStatus(InfrastructureBase):
    """
    PostgreSQL-backed system state storage.
    Used for operations tracking and readiness checks.
    """

    __tablename__ = "system_status"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONBType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(key={self.key!r})>"


class CacheEntry(InfrastructureBase):
    """
    PostgreSQL-backed key-value cache with TTL support.

    NOTE: Periodic cleanup of expired entries should be handled externally
    (e.g., a scheduled task running DELETE WHERE expires_at < now()).
    """

    __tablename__ = "cache_entries"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(key={self.key!r})>"


class SystemContent(InfrastructureBase):
    """Admin-managed content (reviews, changelog, legal, etc.)."""

    __tablename__ = "system_content"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    content_type: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[dict] = mapped_column(JSONBType, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id!r})>"
