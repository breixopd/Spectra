"""Add DISMISSED and RETEST_PENDING to FindingStatus enum and index on status

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "g7h8i9j0k1l2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add missing enum values — PostgreSQL only
    op.execute("ALTER TYPE findingstatus ADD VALUE IF NOT EXISTS 'DISMISSED'")
    op.execute("ALTER TYPE findingstatus ADD VALUE IF NOT EXISTS 'RETEST_PENDING'")
    # Add missing index
    op.create_index("ix_findings_status", "findings", ["status"])


def downgrade() -> None:
    op.drop_index("ix_findings_status", table_name="findings")
    # Note: PostgreSQL doesn't support removing enum values
