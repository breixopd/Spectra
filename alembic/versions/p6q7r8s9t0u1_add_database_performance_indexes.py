"""add database performance indexes

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-03-12

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p6q7r8s9t0u1"
down_revision: str | None = "o5p6q7r8s9t0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Composite index for finding reports: query by target + severity
    op.create_index("ix_findings_target_id_severity", "findings", ["target_id", "severity"])

    # Composite index for audit trail: query by user + time
    op.create_index("ix_audit_logs_user_id_created_at", "audit_logs", ["user_id", "created_at"])

    # Single-column index for API key lookups by prefix
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("ix_audit_logs_user_id_created_at", table_name="audit_logs")
    op.drop_index("ix_findings_target_id_severity", table_name="findings")
