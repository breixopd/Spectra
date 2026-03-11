"""Add composite indexes for missions and findings.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-03-11

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_missions_user_id_status", "missions", ["user_id", "status"])
    op.create_index("ix_findings_user_id_severity", "findings", ["user_id", "severity"])


def downgrade() -> None:
    op.drop_index("ix_findings_user_id_severity", table_name="findings")
    op.drop_index("ix_missions_user_id_status", table_name="missions")
