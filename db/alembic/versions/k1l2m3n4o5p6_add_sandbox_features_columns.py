"""Add sandbox features columns (tiers, networks, heartbeat, priority, escalation)

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-03-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "k1l2m3n4o5p6"
down_revision: str | None = "j0k1l2m3n4o5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sandbox table — new columns for features
    op.add_column("sandboxes", sa.Column("resource_tier", sa.String(), nullable=True, server_default="medium"))
    op.add_column("sandboxes", sa.Column("network_id", sa.String(), nullable=True))
    op.add_column("sandboxes", sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sandboxes", sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=True))
    op.add_column("sandboxes", sa.Column("escalated", sa.Boolean(), nullable=False, server_default="false"))
    op.create_index("ix_sandboxes_user_id", "sandboxes", ["user_id"])

    # JobQueue table — priority column for ordered dequeue
    op.add_column("job_queue", sa.Column("priority", sa.Integer(), nullable=False, server_default="5"))
    op.create_index("ix_job_queue_priority", "job_queue", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_job_queue_priority", table_name="job_queue")
    op.drop_column("job_queue", "priority")

    op.drop_index("ix_sandboxes_user_id", table_name="sandboxes")
    op.drop_column("sandboxes", "escalated")
    op.drop_column("sandboxes", "user_id")
    op.drop_column("sandboxes", "last_heartbeat")
    op.drop_column("sandboxes", "network_id")
    op.drop_column("sandboxes", "resource_tier")
