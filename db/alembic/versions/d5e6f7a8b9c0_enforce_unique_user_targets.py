"""Enforce one normalized target address per user.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-17
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def _remap_duplicate_target_references(table_name: str) -> None:
    """Point child rows at the oldest target before duplicate targets are removed."""
    op.execute(
        sa.text(
            f"""
            WITH ranked AS (
                SELECT id,
                       first_value(id) OVER (
                           PARTITION BY user_id, address
                           ORDER BY created_at ASC, id ASC
                       ) AS canonical_id
                FROM targets
                WHERE user_id IS NOT NULL
            )
            UPDATE {table_name} AS child
            SET target_id = ranked.canonical_id
            FROM ranked
            WHERE child.target_id = ranked.id
              AND ranked.id <> ranked.canonical_id
            """
        )
    )


def upgrade() -> None:
    """Normalize historical addresses, merge duplicates, then enforce uniqueness."""
    # TargetCreate canonicalizes hostnames and IPv6. Normalize historical rows
    # first so the unique index reflects the public API's identity rules.
    op.execute(sa.text("UPDATE targets SET address = lower(address) WHERE user_id IS NOT NULL"))
    _remap_duplicate_target_references("findings")
    _remap_duplicate_target_references("exploits")
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY user_id, address
                           ORDER BY created_at ASC, id ASC
                       ) AS position
                FROM targets
                WHERE user_id IS NOT NULL
            )
            DELETE FROM targets
            USING ranked
            WHERE targets.id = ranked.id
              AND ranked.position > 1
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_targets_user_address_ci
            ON targets (user_id, lower(address))
            WHERE user_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("uq_targets_user_address_ci", table_name="targets", if_exists=True)
