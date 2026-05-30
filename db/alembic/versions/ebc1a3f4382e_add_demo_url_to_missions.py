"""Add demo_url to missions.

Revision ID: ebc1a3f4382e
Revises: a1b2c3d4e5f6
Create Date: 2026-05-03

"""

import sqlalchemy as sa
from alembic import op

revision: str = "d3m0urlv001"
down_revision: str | None = "m1l3st0n35v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column("demo_url", sa.String(512), nullable=True, server_default=None),
    )


def downgrade() -> None:
    op.drop_column("missions", "demo_url")
