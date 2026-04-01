"""Merge migration branches into a single head.

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1, n5o6p7q8r9s0
Create Date: 2026-04-01

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "p7q8r9s0t1u2"
down_revision: Union[str, Sequence[str], None] = ("o6p7q8r9s0t1", "n5o6p7q8r9s0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
