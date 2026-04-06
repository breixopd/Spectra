"""Add index on targets.status and composite index on usage_records.

Revision ID: o6p7q8r9s0t1
Revises: m4n5o6p7q8r9
Create Date: 2026-04-01

postgresql_concurrently=True avoids table locking on live databases.
CONCURRENTLY requires running outside a transaction block.

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "o6p7q8r9s0t1"
down_revision: str | None = "m4n5o6p7q8r9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_targets_status",
            "targets",
            ["status"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_usage_records_user_period",
            "usage_records",
            ["user_id", "period_start", "period_type"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_usage_records_user_period",
            table_name="usage_records",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_targets_status",
            table_name="targets",
            postgresql_concurrently=True,
            if_exists=True,
        )
