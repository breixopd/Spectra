import json
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import String as SAString


class InfrastructureBase(DeclarativeBase):
    pass

class JSONBType(TypeDecorator):
    """Fallback JSONB type for SQLite testing."""
    impl = SAString
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(SAString())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
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


class JobQueue(InfrastructureBase):
    """
    PostgreSQL-backed job queue.
    Replaces ARQ for background task execution.
    """

    __tablename__ = "job_queue"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    queue_name: Mapped[str] = mapped_column(String, nullable=False, default="default", index=True)
    function: Mapped[str] = mapped_column(String, nullable=False)
    args: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    kwargs: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)  # queued, in_progress, completed, failed
    result: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONBType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True) # in seconds


class SystemStatus(InfrastructureBase):
    """
    PostgreSQL-backed system state storage.
    Used for operations tracking and readiness checks.
    """

    __tablename__ = "system_status"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONBType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class CacheEntry(InfrastructureBase):
    """
    PostgreSQL-backed key-value cache with TTL support.

    NOTE: Periodic cleanup of expired entries should be handled externally
    (e.g., a scheduled task running DELETE WHERE expires_at < now()).
    """

    __tablename__ = "cache_entries"

    key: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
