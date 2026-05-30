"""merge heads

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f7, a6b7c8d9e0f1, ab1cd2ef3gh4, h1i2j3k4l5m6
Create Date: 2026-04-08

"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g7"
down_revision: tuple[str, ...] = ("a1b2c3d4e5f7", "a6b7c8d9e0f1", "ab1cd2ef3gh4", "h1i2j3k4l5m6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
