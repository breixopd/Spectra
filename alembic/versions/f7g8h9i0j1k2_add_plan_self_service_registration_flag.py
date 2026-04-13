"""Add explicit self-service registration flag to plans.

Revision ID: f7g8h9i0j1k2
Revises: e5f6g7h8i9j0
Create Date: 2026-04-13 00:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "f7g8h9i0j1k2"
down_revision = "e5f6g7h8i9j0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("allow_self_service_registration", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("plans", "allow_self_service_registration")