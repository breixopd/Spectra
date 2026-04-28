"""Remove warm pool size and image-scan-enabled from admin-managed config.

Revision ID: x5y6z7a8b9c0
Revises: u3v4w5x6y7z8

Warm pool target is derived from sandbox_worker nodes; Grype scans always run when available.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "x5y6z7a8b9c0"
down_revision: str | Sequence[str] | None = "u3v4w5x6y7z8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = ("SANDBOX_WARM_POOL_SIZE", "SANDBOX_IMAGE_SCAN_ENABLED")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM system_config WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(_KEYS)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    rows = [
        (
            "SANDBOX_WARM_POOL_SIZE",
            "2",
            False,
            "Legacy — warm pool size is now derived from sandbox_worker nodes",
        ),
        (
            "SANDBOX_IMAGE_SCAN_ENABLED",
            "true",
            False,
            "Legacy — image scanning is always on when Grype is available",
        ),
    ]
    for key, value, is_secret, description in rows:
        conn.execute(
            sa.text(
                "INSERT INTO system_config (id, key, value, is_secret, description, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :key, :value, :is_secret, :description, now(), now()) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value, "is_secret": is_secret, "description": description},
        )
