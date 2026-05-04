"""Rename roles: operator→staff, viewer→user.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-04-11
"""

from alembic import op

revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE users SET role = 'staff' WHERE role = 'operator'")
    op.execute("UPDATE users SET role = 'user' WHERE role = 'viewer'")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user'")


def downgrade():
    op.execute("UPDATE users SET role = 'operator' WHERE role = 'staff'")
    op.execute("UPDATE users SET role = 'viewer' WHERE role = 'user'")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'operator'")
