"""Add processing_restricted column to users for GDPR Art. 18.

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op

revision = "y4z5a6b7c8d9"
down_revision = "x3y4z5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("processing_restricted", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "processing_restricted")
