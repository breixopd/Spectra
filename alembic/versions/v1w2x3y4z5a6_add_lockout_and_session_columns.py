"""Add lockout, session invalidation, and email verification columns to users.

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

revision = "v1w2x3y4z5a6"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("login_fail_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("invalidated_before", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.drop_column("users", "email_verified")
    op.drop_column("users", "invalidated_before")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "login_fail_count")
