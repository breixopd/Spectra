"""Remove SANDBOX_AUTO_BUILD_IMAGE from admin-managed config (always-on behavior).

Revision ID: u3v4w5x6y7z8
Revises: s1t2u3v4w5x6
Create Date: 2026-04-28

Golden image rebuild on plugin change is platform behavior, not a toggle.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "u3v4w5x6y7z8"
down_revision: str | Sequence[str] | None = "s1t2u3v4w5x6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM system_config WHERE key = :k"), {"k": "SANDBOX_AUTO_BUILD_IMAGE"})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO system_config (id, key, value, is_secret, description, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :key, :value, :is_secret, :description, now(), now()) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {
            "key": "SANDBOX_AUTO_BUILD_IMAGE",
            "value": "true",
            "is_secret": False,
            "description": "Auto-rebuild golden image on plugin change (legacy row)",
        },
    )
