"""Remove deployment-owned sandbox config from runtime DB settings.

Revision ID: s1t2u3v4w5x6
Revises: r0s1t2u3v4w5
Create Date: 2026-04-28 22:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "s1t2u3v4w5x6"
down_revision: str | Sequence[str] | None = "r0s1t2u3v4w5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTERNAL_KEYS = ("SANDBOX_IMAGE", "SANDBOX_NETWORK", "SANDBOX_PLUGINS_VOLUME")


def upgrade() -> None:
    """Remove env/deployment-owned keys from admin-managed system_config."""
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM system_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(_INTERNAL_KEYS)},
    )


def downgrade() -> None:
    """Restore previous defaults for local rollback only."""
    conn = op.get_bind()
    defaults = {
        "SANDBOX_IMAGE": ("spectra-tools", "Sandbox Docker image name"),
        "SANDBOX_NETWORK": ("spectra-network", "Sandbox Docker network name"),
        "SANDBOX_PLUGINS_VOLUME": ("spectra_plugins", "Sandbox plugins Docker volume"),
    }
    for key, (value, description) in defaults.items():
        conn.exec_driver_sql(
            """
            INSERT INTO system_config (id, key, value, is_secret, description, created_at, updated_at)
            VALUES (gen_random_uuid(), %(key)s, %(value)s, false, %(description)s, now(), now())
            ON CONFLICT (key) DO NOTHING
            """,
            {"key": key, "value": value, "description": description},
        )
