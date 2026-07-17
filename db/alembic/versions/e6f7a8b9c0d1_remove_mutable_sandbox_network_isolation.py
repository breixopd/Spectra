"""Make sandbox network isolation deployment-owned and mandatory.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove legacy admin control that could disable an isolation boundary."""
    op.execute(
        sa.text(
            """
            DELETE FROM system_config
            WHERE key IN ('SANDBOX_NETWORK_ISOLATION', 'SANDBOX_PLUGINS_VOLUME')
            """
        )
    )


def downgrade() -> None:
    """Restore the old value only for an explicit database rollback."""
    op.execute(
        sa.text(
            """
            INSERT INTO system_config (id, key, value, is_secret, description, created_at, updated_at)
            VALUES (
                gen_random_uuid(),
                'SANDBOX_NETWORK_ISOLATION',
                'true',
                false,
                'Legacy sandbox network-isolation setting',
                now(),
                now()
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )
