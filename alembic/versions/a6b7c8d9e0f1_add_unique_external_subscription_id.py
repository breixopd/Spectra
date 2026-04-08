"""add unique constraint on external_subscription_id

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-04-08 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a6b7c8d9e0f1"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_subscriptions_external_subscription_id",
        "subscriptions",
        ["external_subscription_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_subscriptions_external_subscription_id",
        "subscriptions",
        type_="unique",
    )
