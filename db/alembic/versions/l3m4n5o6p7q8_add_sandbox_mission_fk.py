"""Add FK constraint on sandboxes.mission_id referencing missions.

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-04-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l3m4n5o6p7q8"
down_revision: str | None = "k2l3m4n5o6p7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "sandboxes",
        "mission_id",
        existing_type=sa.String(),
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="mission_id::uuid",
    )
    op.create_foreign_key(
        "fk_sandboxes_mission_id_missions",
        "sandboxes",
        "missions",
        ["mission_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sandboxes_mission_id_missions",
        "sandboxes",
        type_="foreignkey",
    )
    op.alter_column(
        "sandboxes",
        "mission_id",
        existing_type=postgresql.UUID(as_uuid=False),
        type_=sa.String(),
        postgresql_using="mission_id::text",
    )
