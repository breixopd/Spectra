"""Add sandboxes table for per-mission ephemeral containers

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j0k1l2m3n4o5"
down_revision: str | None = "i9j0k1l2m3n4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sandboxes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("mission_id", sa.String(), nullable=False),
        sa.Column("container_id", sa.String(), nullable=False),
        sa.Column("container_name", sa.String(), nullable=False),
        sa.Column("queue_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="creating"),
        sa.Column("image", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("destroyed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id"),
    )
    op.create_index("ix_sandboxes_mission_id", "sandboxes", ["mission_id"])
    op.create_index("ix_sandboxes_queue_name", "sandboxes", ["queue_name"])


def downgrade() -> None:
    op.drop_index("ix_sandboxes_queue_name", table_name="sandboxes")
    op.drop_index("ix_sandboxes_mission_id", table_name="sandboxes")
    op.drop_table("sandboxes")
