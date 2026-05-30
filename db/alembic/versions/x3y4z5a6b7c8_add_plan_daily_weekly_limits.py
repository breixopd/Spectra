"""Add daily and weekly mission limits to plans.

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op

revision = "x3y4z5a6b7c8"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("max_missions_per_day", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("plans", sa.Column("max_missions_per_week", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("plans", "max_missions_per_week")
    op.drop_column("plans", "max_missions_per_day")
