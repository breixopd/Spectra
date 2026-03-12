"""Add plans, subscriptions, api_keys, and usage_records tables.

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-03-09

"""


import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l2m3n4o5p6q7"
down_revision: str | None = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plans table
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_concurrent_missions", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("max_missions_per_month", sa.Integer(), nullable=True),
        sa.Column("max_targets", sa.Integer(), nullable=True),
        sa.Column("max_api_requests_per_hour", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("max_api_requests_per_day", sa.Integer(), nullable=False, server_default=sa.text("1000")),
        sa.Column("sandbox_resource_tier", sa.String(50), nullable=False, server_default="medium"),
        sa.Column("sandbox_max_containers", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("max_storage_mb", sa.Integer(), nullable=False, server_default=sa.text("500")),
        sa.Column("features", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_subscription_id", sa.String(255), nullable=True),
        sa.Column("external_customer_id", sa.String(255), nullable=True),
        sa.Column("payment_provider", sa.String(50), nullable=True),
        sa.Column("metadata_", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # API keys table
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(10), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Usage records table
    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("api_requests", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("missions_started", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sandbox_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_tokens_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("storage_used_mb", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Add plan_id and api_key_prefix to users table
    op.add_column("users", sa.Column("plan_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("plans.id", ondelete="SET NULL"), nullable=True))
    op.create_index(op.f("ix_users_plan_id"), "users", ["plan_id"])
    op.add_column("users", sa.Column("api_key_prefix", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_index(op.f("ix_users_plan_id"), table_name="users")
    op.drop_column("users", "api_key_prefix")
    op.drop_column("users", "plan_id")
    op.drop_table("usage_records")
    op.drop_table("api_keys")
    op.drop_table("subscriptions")
    op.drop_table("plans")
