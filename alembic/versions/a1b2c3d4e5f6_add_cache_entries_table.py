"""Add infrastructure tables (cache, job queue, system status)

Revision ID: a1b2c3d4e5f6
Revises: 5078f1069d4e
Create Date: 2026-03-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "5078f1069d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cache entries table
    op.create_table(
        "cache_entries",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(op.f("ix_cache_entries_key"), "cache_entries", ["key"], unique=False)

    # Job queue table (replaces ARQ/Redis)
    op.create_table(
        "job_queue",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("queue_name", sa.String(), nullable=False, server_default="default"),
        sa.Column("function", sa.String(), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("kwargs", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_queue_queue_name", "job_queue", ["queue_name"])
    op.create_index("ix_job_queue_status", "job_queue", ["status"])

    # System cache (JSONB key-value store)
    op.create_table(
        "system_cache",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )

    # System status
    op.create_table(
        "system_status",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("system_status")
    op.drop_table("system_cache")
    op.drop_index("ix_job_queue_status", table_name="job_queue")
    op.drop_index("ix_job_queue_queue_name", table_name="job_queue")
    op.drop_table("job_queue")
    op.drop_index(op.f("ix_cache_entries_key"), table_name="cache_entries")
    op.drop_table("cache_entries")
