"""Add rules_of_engagement table.

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-03

"""

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rules_of_engagement",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("mission_id", sa.UUID(), nullable=False),
        sa.Column("authorized_targets", sa.JSON(), nullable=True),
        sa.Column("excluded_targets", sa.JSON(), nullable=True),
        sa.Column("authorized_actions", sa.JSON(), nullable=True),
        sa.Column("prohibited_actions", sa.JSON(), nullable=True),
        sa.Column("max_scan_intensity", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("data_exfiltration_allowed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("max_exfiltration_bytes", sa.Integer(), nullable=True),
        sa.Column("allow_persistence", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notification_email", sa.String(255), nullable=True),
        sa.Column("operator_signoff_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("additional_constraints", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id"),
    )
    op.create_index("ix_roe_mission_id", "rules_of_engagement", ["mission_id"])
    op.create_foreign_key(
        "fk_roe_mission_id",
        "rules_of_engagement",
        "missions",
        ["mission_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_roe_mission_id", "rules_of_engagement", type_="foreignkey")
    op.drop_index("ix_roe_mission_id", table_name="rules_of_engagement")
    op.drop_table("rules_of_engagement")