"""Encrypt BYOK API keys in user_preferences.

Revision ID: j1k2l3m4n5o6
Revises: w2x3y4z5a6b7
Create Date: 2026-04-01

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, None] = "w2x3y4z5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen columns from VARCHAR(512) to TEXT to accommodate Fernet tokens
    op.alter_column(
        "user_preferences",
        "llm_api_key",
        existing_type=sa.String(512),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "user_preferences",
        "embedding_api_key",
        existing_type=sa.String(512),
        type_=sa.Text(),
        existing_nullable=True,
    )

    # Encrypt any plaintext values that pre-date service-layer encryption
    bind = op.get_bind()
    try:
        from app.core.security import encrypt_byok_key

        rows = bind.execute(
            sa.text(
                "SELECT user_id, llm_api_key, embedding_api_key "
                "FROM user_preferences "
                "WHERE llm_api_key IS NOT NULL OR embedding_api_key IS NOT NULL"
            )
        ).fetchall()

        for row in rows:
            user_id, llm_key, embed_key = row
            updates: dict = {}
            if llm_key and not llm_key.startswith("gAAAAA"):
                updates["llm_api_key"] = encrypt_byok_key(llm_key)
            if embed_key and not embed_key.startswith("gAAAAA"):
                updates["embedding_api_key"] = encrypt_byok_key(embed_key)
            if updates:
                set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                updates["user_id"] = user_id
                bind.execute(
                    sa.text(
                        f"UPDATE user_preferences SET {set_clause} WHERE user_id = :user_id"
                    ),
                    updates,
                )
    except Exception:
        # Skip if encryption module is unavailable (e.g., minimal CI environment)
        pass


def downgrade() -> None:
    op.alter_column(
        "user_preferences",
        "llm_api_key",
        existing_type=sa.Text(),
        type_=sa.String(512),
        existing_nullable=True,
    )
    op.alter_column(
        "user_preferences",
        "embedding_api_key",
        existing_type=sa.Text(),
        type_=sa.String(512),
        existing_nullable=True,
    )
