"""Add unique period constraint to usage records.

Revision ID: p8q9r0s1t2u3
Revises: o6p7q8r9s0t1
Create Date: 2026-04-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "p8q9r0s1t2u3"
down_revision: str | None = "o6p7q8r9s0t1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_records_user_period
        ON usage_records (user_id, period_type, period_start)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_usage_records_user_period")
