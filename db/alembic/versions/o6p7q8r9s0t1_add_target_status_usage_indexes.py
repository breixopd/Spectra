"""Add index on targets.status and composite index on usage_records.

Revision ID: o6p7q8r9s0t1
Revises: m4n5o6p7q8r9
Create Date: 2026-04-01

Uses normal (non-concurrent) index creation inside a transaction.
For live databases with large tables, create indexes manually with
CONCURRENTLY first — the IF NOT EXISTS clause will skip them here.

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "o6p7q8r9s0t1"
down_revision: str | None = "m4n5o6p7q8r9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_targets_status",
        "targets",
        ["status"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_usage_records_user_period",
        "usage_records",
        ["user_id", "period_start", "period_type"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_user_period", table_name="usage_records", if_exists=True)
    op.drop_index("ix_targets_status", table_name="targets", if_exists=True)
