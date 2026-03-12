"""User plans and subscription models for tiered access control."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.infrastructure import JSONBType


class Plan(Base):
    """Admin-configurable subscription tiers."""

    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Limits
    max_concurrent_missions: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_missions_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_targets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_api_requests_per_hour: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_api_requests_per_day: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    sandbox_resource_tier: Mapped[str] = mapped_column(
        String(50), default="medium", nullable=False, server_default="medium"
    )
    sandbox_max_containers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_storage_mb: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    features: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    def __repr__(self) -> str:
        return f"<Plan(id={self.id}, name={self.name})>"


class Subscription(Base):
    """Tracks which plan a user is on."""

    __tablename__ = "subscriptions"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        String, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, user_id={self.user_id}, status={self.status})>"


class ApiKey(Base):
    """Per-user API keys for programmatic access."""

    __tablename__ = "api_keys"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    scopes: Mapped[list | None] = mapped_column(JSONBType, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ApiKey only needs created_at (inherited from Base which also provides updated_at)

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, prefix={self.key_prefix}, user_id={self.user_id})>"


class UsageRecord(Base):
    """Tracks API/resource usage per user per period."""

    __tablename__ = "usage_records"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    api_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missions_started: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sandbox_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_used_mb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<UsageRecord(id={self.id}, user_id={self.user_id}, period={self.period_type})>"
