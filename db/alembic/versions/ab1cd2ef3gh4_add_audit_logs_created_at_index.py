"""add audit_logs created_at index

Revision ID: ab1cd2ef3gh4
Revises: aa1bb2cc3dd4
Create Date: 2026-04-08
"""

from alembic import op

revision = "ab1cd2ef3gh4"
down_revision = "aa1bb2cc3dd4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_audit_logs_created_at",
        "audit_logs",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
