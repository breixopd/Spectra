"""Restrict per-mission sandbox roles to their own queue rows.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable role-name-bound row-level security for ephemeral sandboxes."""
    op.execute("ALTER TABLE job_queue ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sandbox_job_queue_per_mission ON job_queue")
    op.execute(
        """
        CREATE POLICY sandbox_job_queue_per_mission ON job_queue
        FOR ALL TO PUBLIC
        USING (
            current_user !~ '^spectra_sandbox_[0-9a-f]{32}$'
            OR queue_name = 'mission_' || substring(current_user FROM 17 FOR 8)
        )
        WITH CHECK (
            current_user !~ '^spectra_sandbox_[0-9a-f]{32}$'
            OR queue_name = 'mission_' || substring(current_user FROM 17 FOR 8)
        )
        """
    )


def downgrade() -> None:
    """Remove the sandbox-specific row-level policy on explicit rollback."""
    op.execute("DROP POLICY IF EXISTS sandbox_job_queue_per_mission ON job_queue")
    op.execute("ALTER TABLE job_queue DISABLE ROW LEVEL SECURITY")
