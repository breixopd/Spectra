"""Add retry_count and max_retries to job_queue.

Revision ID: o5p6q7r8s9t0
Revises: m1n2o3p4q5r6
Create Date: 2026-03-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "o5p6q7r8s9t0"
down_revision: str | None = "m1n2o3p4q5r6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_queue", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("job_queue", sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"))


def downgrade() -> None:
    op.drop_column("job_queue", "max_retries")
    op.drop_column("job_queue", "retry_count")
