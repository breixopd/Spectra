"""Change server_nodes.ssh_user server_default from root to ubuntu.

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-04-01

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "server_nodes",
        "ssh_user",
        existing_type=sa.String(100),
        server_default="ubuntu",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "server_nodes",
        "ssh_user",
        existing_type=sa.String(100),
        server_default="root",
        existing_nullable=False,
    )
