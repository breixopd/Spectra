"""Add training_opt_in and training_opt_in_locked_until to users.

Merges both migration chains (d3m0urlv001 and z0a1b2c3d4e5).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "train_opt_v1"
down_revision: str | Sequence[str] | None = ("d3m0urlv001", "z0a1b2c3d4e5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("training_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("training_opt_in_locked_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "training_opt_in_locked_until")
    op.drop_column("users", "training_opt_in")
