"""Rename roles: operator→staff, viewer→user.

Revision ID: j0k1l2m3n4o5
Revises: z5a6b7c8d9e0
Create Date: 2026-04-11
"""

from alembic import op

revision = "j0k1l2m3n4o5"
down_revision = "z5a6b7c8d9e0"
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
