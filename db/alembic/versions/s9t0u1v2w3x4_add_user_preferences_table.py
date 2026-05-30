"""Add user_preferences table.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-03-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "s9t0u1v2w3x4"
down_revision = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        # BYOK
        sa.Column("llm_api_key", sa.String(512), nullable=True),
        sa.Column("llm_api_base_url", sa.String(512), nullable=True),
        sa.Column("llm_model", sa.String(128), nullable=True),
        sa.Column("embedding_api_key", sa.String(512), nullable=True),
        sa.Column("embedding_api_base_url", sa.String(512), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        # Notifications
        sa.Column("email_notifications", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("webhook_url", sa.String(512), nullable=True),
        sa.Column("notify_on_mission_complete", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notify_on_critical_finding", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # Mission defaults
        sa.Column("default_scan_mode", sa.String(20), nullable=False, server_default=sa.text("'autonomous'")),
        sa.Column("default_report_format", sa.String(10), nullable=False, server_default=sa.text("'pdf'")),
        # UI
        sa.Column("timezone", sa.String(50), nullable=False, server_default=sa.text("'UTC'")),
        # Extensible
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_user_preferences_user_id"), "user_preferences", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_preferences_user_id"), table_name="user_preferences")
    op.drop_table("user_preferences")
