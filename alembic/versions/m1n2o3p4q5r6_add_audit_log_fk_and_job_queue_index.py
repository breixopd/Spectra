"""Add audit_log FK and job_queue composite index.

Revision ID: m1n2o3p4q5r6
Revises: l2m3n4o5p6q7
Create Date: 2026-03-11 00:00:00.000000
"""

from alembic import op

# revision identifiers
revision = "m1n2o3p4q5r6"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_audit_logs_user_id",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index(
        "ix_job_queue_status_queue",
        "job_queue",
        ["status", "queue_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_queue_status_queue", table_name="job_queue")
    op.drop_constraint("fk_audit_logs_user_id", "audit_logs", type_="foreignkey")
