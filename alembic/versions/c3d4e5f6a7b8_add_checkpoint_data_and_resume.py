"""add checkpoint_data and resume to missions

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("missions", sa.Column("checkpoint_data", sa.JSON(), nullable=True))
    op.add_column("missions", sa.Column("resume", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("missions", "resume")
    op.drop_column("missions", "checkpoint_data")
