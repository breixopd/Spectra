"""add stripe_price_id to plans

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-03-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "n1o2p3q4r5s6"
down_revision = "s9t0u1v2w3x4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("stripe_price_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "stripe_price_id")
