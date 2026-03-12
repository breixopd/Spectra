"""Add indexes on timestamp columns used by cleanup queries.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-03-12

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q7r8s9t0u1v2"
down_revision: str | None = "p6q7r8s9t0u1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Speed up periodic cleanup of expired system cache entries
    op.create_index("ix_system_cache_expires_at", "system_cache", ["expires_at"])

    # Speed up periodic cleanup of expired cache entries
    op.create_index("ix_cache_entries_expires_at", "cache_entries", ["expires_at"])

    # Speed up completed/dead-letter job pruning
    op.create_index("ix_job_queue_completed_at", "job_queue", ["completed_at"])

    # Speed up audit log pruning by created_at (existing composite index
    # ix_audit_logs_user_id_created_at has user_id as leading column)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_job_queue_completed_at", table_name="job_queue")
    op.drop_index("ix_cache_entries_expires_at", table_name="cache_entries")
    op.drop_index("ix_system_cache_expires_at", table_name="system_cache")
