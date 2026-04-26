"""add missions created_at index

Revision ID: p9q0r1s2t3u4
Revises: p8q9r0s1t2u3
Create Date: 2026-04-27
"""

from alembic import op

revision = "p9q0r1s2t3u4"
down_revision = "p8q9r0s1t2u3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_missions_created_at",
        "missions",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_missions_created_at", table_name="missions")
