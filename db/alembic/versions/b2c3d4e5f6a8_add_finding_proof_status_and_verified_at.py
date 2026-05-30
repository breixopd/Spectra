"""Add proof_status and verified_at to findings.

Revision ID: b2c3d4e5f6a8
Revises: fix_jq_cols
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a8"
down_revision: str | None = "fix_jq_cols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

proof_status_enum = sa.Enum(
    "candidate",
    "needs_verification",
    "verified",
    "not_reproducible",
    name="proofstatus",
)


def upgrade() -> None:
    proof_status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "findings",
        sa.Column(
            "proof_status",
            proof_status_enum,
            nullable=False,
            server_default="candidate",
        ),
    )
    op.add_column(
        "findings",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_findings_proof_status", "findings", ["proof_status"])


def downgrade() -> None:
    op.drop_index("ix_findings_proof_status", table_name="findings")
    op.drop_column("findings", "verified_at")
    op.drop_column("findings", "proof_status")
    proof_status_enum.drop(op.get_bind(), checkfirst=True)
