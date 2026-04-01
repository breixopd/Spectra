"""Add FK constraint on sandboxes.mission_id referencing missions.

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-04-01

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
