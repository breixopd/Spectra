"""add rollback_snapshots table

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-03-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "w2x3y4z5a6b7"
down_revision: str | None = "v1w2x3y4z5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rollback_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("target_entity_type", sa.String(50), nullable=False),
        sa.Column("target_entity_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("before_state", sa.Text(), nullable=False),
        sa.Column("rolled_back", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("rolled_back_by", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rollback_snapshots_actor_user_id",
        "rollback_snapshots",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_rollback_snapshots_target_entity_id",
        "rollback_snapshots",
        ["target_entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rollback_snapshots_target_entity_id", table_name="rollback_snapshots")
    op.drop_index("ix_rollback_snapshots_actor_user_id", table_name="rollback_snapshots")
    op.drop_table("rollback_snapshots")
