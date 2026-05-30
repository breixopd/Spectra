"""Repair user_preferences schema.

Revision ID: q9r0s1t2u3v4
Revises: f7g8h9i0j1k2, p9q0r1s2t3u4
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "q9r0s1t2u3v4"
down_revision: str | Sequence[str] | None = ("f7g8h9i0j1k2", "p9q0r1s2t3u4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("user_preferences"):
        op.create_table(
            "user_preferences",
            sa.Column("id", sa.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
            sa.Column("llm_api_key", sa.Text(), nullable=True),
            sa.Column("llm_api_base_url", sa.String(512), nullable=True),
            sa.Column("llm_model", sa.String(128), nullable=True),
            sa.Column("embedding_api_key", sa.Text(), nullable=True),
            sa.Column("embedding_api_base_url", sa.String(512), nullable=True),
            sa.Column("embedding_model", sa.String(128), nullable=True),
            sa.Column("email_notifications", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("announcements_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("webhook_url", sa.String(512), nullable=True),
            sa.Column("notify_on_mission_complete", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("notify_on_critical_finding", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("default_scan_mode", sa.String(20), nullable=False, server_default=sa.text("'autonomous'")),
            sa.Column("default_report_format", sa.String(10), nullable=False, server_default=sa.text("'pdf'")),
            sa.Column("timezone", sa.String(50), nullable=False, server_default=sa.text("'UTC'")),
            sa.Column("share_training_data", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_user_preferences_user_id"), "user_preferences", ["user_id"], unique=True)
        return

    columns = _columns("user_preferences")
    if "announcements_opt_in" not in columns:
        op.add_column(
            "user_preferences",
            sa.Column("announcements_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
    if "share_training_data" not in columns:
        op.add_column(
            "user_preferences",
            sa.Column("share_training_data", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    columns = _columns("user_preferences")
    if "share_training_data" in columns:
        op.drop_column("user_preferences", "share_training_data")
