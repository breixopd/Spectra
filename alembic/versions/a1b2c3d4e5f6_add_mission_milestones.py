"""Add mission milestones.

Revision ID: m1l3st0n35v1
Revises: b1c2d3e4f5a6
Create Date: 2026-05-03 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "m1l3st0n35v1"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column("milestones", sa.JSON(), nullable=True, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("missions", "milestones")