"""Backfill rag_documents.metadata user_id from owning mission.

Revision ID: z0a1b2c3d4e5
Revises: y6z7a8b9c0d1

``rag_documents.session_id`` stores the mission id for mission-scoped rows.
This migration copies ``missions.user_id`` into ``metadata->>'user_id'`` when
missing so tenant-scoped RAG filters apply to historical rows.

Idempotent: only updates rows where user_id is absent or blank.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "z0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "y6z7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    rag = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'rag_documents'"
        )
    ).first()
    if not rag:
        return
    missions = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'missions'"
        )
    ).first()
    if not missions:
        return

    conn.execute(
        sa.text(
            """
            UPDATE rag_documents rd
            SET metadata = COALESCE(rd.metadata, '{}'::jsonb)
                || jsonb_build_object('user_id', m.user_id::text)
            FROM missions m
            WHERE rd.session_id IS NOT NULL
              AND m.user_id IS NOT NULL
              AND trim(rd.session_id::text) = trim(m.id::text)
              AND (
                  rd.metadata->>'user_id' IS NULL
                  OR btrim(rd.metadata->>'user_id') = ''
              )
            """
        )
    )


def downgrade() -> None:
    # Non-reversible: cannot know which user_id values were backfilled vs authored.
    pass
