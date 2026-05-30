"""Fix audit_log user_id FK to SET NULL on delete.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-03-12 00:00:00.000000
"""

from alembic import op

# revision identifiers
revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_audit_logs_user_id", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "fk_audit_logs_user_id",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_audit_logs_user_id", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "fk_audit_logs_user_id",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
    )
