"""Add mission feedback columns.

Revision ID: n5o6p7q8r9s0
Revises: v1w2x3y4z5a6
Create Date: 2026-03-26 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "n5o6p7q8r9s0"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("missions", sa.Column("feedback_rating", sa.Integer(), nullable=True))
    op.add_column("missions", sa.Column("feedback_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("missions", "feedback_comment")
    op.drop_column("missions", "feedback_rating")
