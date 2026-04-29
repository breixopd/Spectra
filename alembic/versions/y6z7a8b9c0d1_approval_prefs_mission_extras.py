"""User approval preference, mission playbook/demo/scan_mode; drop REQUIRE_APPROVAL from system_config.

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "y6z7a8b9c0d1"
down_revision: str | Sequence[str] | None = "x5y6z7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM system_config WHERE key = 'REQUIRE_APPROVAL'"))
    op.add_column(
        "user_preferences",
        sa.Column(
            "prefer_mission_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("missions", sa.Column("playbook_id", sa.String(128), nullable=True))
    op.add_column(
        "missions",
        sa.Column("record_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "missions",
        sa.Column("scan_mode", sa.String(20), nullable=False, server_default=sa.text("'autonomous'")),
    )


def downgrade() -> None:
    op.drop_column("missions", "scan_mode")
    op.drop_column("missions", "record_demo")
    op.drop_column("missions", "playbook_id")
    op.drop_column("user_preferences", "prefer_mission_approval")
    op.execute(
        sa.text(
            "INSERT INTO system_config (id, key, value, is_secret, description, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'REQUIRE_APPROVAL', 'false', false, "
            "'Require human approval for high-risk actions', now(), now()) "
            "ON CONFLICT (key) DO NOTHING"
        ),
    )
