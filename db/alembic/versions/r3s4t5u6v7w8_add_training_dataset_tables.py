"""Add training dataset and fine-tuning tables.

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-04-04 03:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "r3s4t5u6v7w8"
down_revision = "q2r3s4t5u6v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_samples",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "mission_id",
            UUID(as_uuid=False),
            sa.ForeignKey("missions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sample_type", sa.String(50), nullable=False, index=True),
        sa.Column("input_text", sa.Text, nullable=False),
        sa.Column("output_text", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("is_anonymized", sa.Boolean, default=True, nullable=False),
        sa.Column("is_approved", sa.Boolean, default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "fine_tuning_jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, default="pending"),
        sa.Column("base_model", sa.String(200), nullable=False),
        sa.Column("sample_count", sa.Integer, default=0, nullable=False),
        sa.Column("sample_types", JSONB, nullable=True),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("provider_job_id", sa.String(255), nullable=True),
        sa.Column("output_model_path", sa.String(500), nullable=True),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_training_samples_type_quality", "training_samples", ["sample_type", "quality_score"])


def downgrade() -> None:
    op.drop_table("fine_tuning_jobs")
    op.drop_table("training_samples")
