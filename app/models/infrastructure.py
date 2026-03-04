from datetime import datetime

import json
from sqlalchemy import Column, DateTime, Integer, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import String as SAString

from app.models.base import Base

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

class SystemCache(Base):
    """
    PostgreSQL-backed key-value cache.
    Replaces Redis cache functionality.
    """

    __tablename__ = "system_cache"

    key = Column(String, primary_key=True)
    value = Column(JSONBType, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JobQueue(Base):
    """
    PostgreSQL-backed job queue.
    Replaces ARQ for background task execution.
    """

    __tablename__ = "job_queue"

    id = Column(String, primary_key=True)
    queue_name = Column(String, nullable=False, default="default", index=True)
    function = Column(String, nullable=False)
    args = Column(JSONBType, nullable=False, default=list)
    kwargs = Column(JSONBType, nullable=False, default=dict)

    status = Column(String, nullable=False, default="queued", index=True)  # queued, in_progress, completed, failed
    result = Column(JSONBType, nullable=True)
    error = Column(Text, nullable=True)

    enqueued_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    timeout = Column(Integer, nullable=True) # in seconds


class SystemStatus(Base):
    """
    PostgreSQL-backed system state storage.
    Replaces Redis hash maps used for operations tracking and readiness checks.
    """

    __tablename__ = "system_status"

    key = Column(String, primary_key=True)
    value = Column(JSONBType, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
