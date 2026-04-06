"""Add indexes to foreign key columns.

Revision ID: j0k1l2m3n4o5
Revises: z5a6b7c8d9e0
Create Date: 2026-04-06
"""

from alembic import op

revision = "j0k1l2m3n4o5"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_training_samples_user_id", "training_samples", ["user_id"])
    op.create_index("ix_fine_tuning_jobs_created_by", "fine_tuning_jobs", ["created_by"])
    op.create_index("ix_rollback_snapshots_rolled_back_by", "rollback_snapshots", ["rolled_back_by"])


def downgrade() -> None:
    op.drop_index("ix_rollback_snapshots_rolled_back_by", table_name="rollback_snapshots")
    op.drop_index("ix_fine_tuning_jobs_created_by", table_name="fine_tuning_jobs")
    op.drop_index("ix_training_samples_user_id", table_name="training_samples")
