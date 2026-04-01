"""Add FK constraint to rollback_snapshots.rolled_back_by.

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-04-01

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_rollback_snapshots_rolled_back_by_users",
        "rollback_snapshots",
        "users",
        ["rolled_back_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_rollback_snapshots_rolled_back_by_users",
        "rollback_snapshots",
        type_="foreignkey",
    )
