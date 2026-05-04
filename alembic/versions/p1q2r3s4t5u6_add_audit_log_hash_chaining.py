"""Add hash chaining to audit logs.

Revision ID: p1q2r3s4t5u6
Revises: n1o2p3q4r5s6
Create Date: 2026-04-03
"""

import sqlalchemy as sa

from alembic import op

revision = "p1q2r3s4t5u6"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("integrity_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("previous_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "previous_hash")
    op.drop_column("audit_logs", "integrity_hash")
