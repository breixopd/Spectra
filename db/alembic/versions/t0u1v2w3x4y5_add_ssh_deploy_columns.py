"""Add SSH deployment columns to server_nodes.

Revision ID: t0u1v2w3x4y5
Revises: n1o2p3q4r5s6
Create Date: 2026-03-13

"""

import sqlalchemy as sa
from alembic import op

revision: str = "t0u1v2w3x4y5"
down_revision: str | None = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "server_nodes",
        sa.Column("ssh_user", sa.String(100), nullable=False, server_default="root"),
    )
    op.add_column(
        "server_nodes",
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default=sa.text("22")),
    )
    op.add_column(
        "server_nodes",
        sa.Column("ssh_key_path", sa.String(500), nullable=True),
    )
    op.add_column(
        "server_nodes",
        sa.Column("deployed_services", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("server_nodes", "deployed_services")
    op.drop_column("server_nodes", "ssh_key_path")
    op.drop_column("server_nodes", "ssh_port")
    op.drop_column("server_nodes", "ssh_user")
