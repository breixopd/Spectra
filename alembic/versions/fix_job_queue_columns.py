"""Add missing job_queue columns (next_retry_at).

Revision ID: fix_jq_cols
Merges from both heads (d3m0urlv001 and z0a1b2c3d4e5).
"""
from collections.abc import Sequence
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = 'fix_jq_cols'
down_revision: Union[str, Sequence[str], None] = ('train_opt_v1',)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('job_queue', sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column('job_queue', 'next_retry_at')
