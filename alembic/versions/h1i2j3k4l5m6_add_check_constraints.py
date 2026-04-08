"""Add check constraints to numeric model columns.

Revision ID: h1i2j3k4l5m6
Revises: j1k2l3m4n5o6
Create Date: 2026-04-08

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h1i2j3k4l5m6"
down_revision: str = "j1k2l3m4n5o6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_findings_cvss_range",
        "findings",
        "cvss_score IS NULL OR (cvss_score >= 0 AND cvss_score <= 10)",
    )
    op.create_check_constraint(
        "ck_missions_feedback_rating_range",
        "missions",
        "feedback_rating IS NULL OR (feedback_rating >= 1 AND feedback_rating <= 5)",
    )
    op.create_check_constraint(
        "ck_server_nodes_weight_nonneg",
        "server_nodes",
        "weight >= 0",
    )
    op.create_check_constraint(
        "ck_server_nodes_current_load_nonneg",
        "server_nodes",
        "current_load >= 0",
    )
    op.create_check_constraint(
        "ck_server_nodes_max_capacity_pos",
        "server_nodes",
        "max_capacity > 0",
    )
    op.create_check_constraint(
        "ck_job_queue_priority_range",
        "job_queue",
        "priority >= 1 AND priority <= 10",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_queue_priority_range", "job_queue", type_="check")
    op.drop_constraint("ck_server_nodes_max_capacity_pos", "server_nodes", type_="check")
    op.drop_constraint("ck_server_nodes_current_load_nonneg", "server_nodes", type_="check")
    op.drop_constraint("ck_server_nodes_weight_nonneg", "server_nodes", type_="check")
    op.drop_constraint("ck_missions_feedback_rating_range", "missions", type_="check")
    op.drop_constraint("ck_findings_cvss_range", "findings", type_="check")
