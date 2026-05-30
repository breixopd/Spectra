"""Repair plan column defaults.

Revision ID: r0s1t2u3v4w5
Revises: q9r0s1t2u3v4
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r0s1t2u3v4w5"
down_revision: str | Sequence[str] | None = "q9r0s1t2u3v4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "plans",
        "is_default",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.alter_column(
        "plans",
        "is_default",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=None,
    )
