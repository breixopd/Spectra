"""Add max_llm_tokens_per_day to plans.

Revision ID: a1b2c3d4e5f7
Revises: z5a6b7c8d9e0
Create Date: 2026-04-08
"""

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("max_llm_tokens_per_day", sa.Integer(), nullable=False, server_default="500000"),
    )


def downgrade() -> None:
    op.drop_column("plans", "max_llm_tokens_per_day")
