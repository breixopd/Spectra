"""Add auto_share_training_data to plans.

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-04-04 03:01:00
"""

import sqlalchemy as sa

from alembic import op

revision = "s4t5u6v7w8x9"
down_revision = "r3s4t5u6v7w8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("auto_share_training_data", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("plans", "auto_share_training_data")
