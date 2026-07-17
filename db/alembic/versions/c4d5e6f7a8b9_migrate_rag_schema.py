"""Move RAG storage ownership from application startup to Alembic.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a8
Create Date: 2026-07-17
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the canonical RAG schema and migrate legacy runtime-created tables."""
    conn = op.get_bind()
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    table_exists = conn.execute(sa.text("SELECT to_regclass('rag_documents') IS NOT NULL")).scalar()
    if not table_exists:
        conn.execute(
            sa.text(
                """
                CREATE TABLE rag_documents (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    cve_id TEXT NULL,
                    severity TEXT NULL,
                    target TEXT NULL,
                    session_id TEXT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    embedding vector NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dimension INTEGER NOT NULL,
                    content_hash TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT ck_rag_documents_embedding_dimension
                        CHECK (vector_dims(embedding) = embedding_dimension)
                )
                """
            )
        )
    else:
        # The legacy startup path used a dimension-constrained vector column.
        # Preserve documents while making dimensions explicit per model profile.
        conn.execute(sa.text("DROP INDEX IF EXISTS idx_rag_embedding_hnsw"))
        embedding_type = conn.execute(
            sa.text(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'rag_documents'
                  AND column_name = 'embedding'
                """
            )
        ).scalar()
        if embedding_type != "vector":
            raise RuntimeError(
                "rag_documents.embedding is not a pgvector column; reindex the legacy RAG corpus before upgrading"
            )

        conn.execute(sa.text("ALTER TABLE rag_documents ALTER COLUMN embedding TYPE vector USING embedding::vector"))
        conn.execute(sa.text("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS embedding_model TEXT"))
        conn.execute(sa.text("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER"))
        conn.execute(sa.text("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS content_hash TEXT"))
        conn.execute(sa.text("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()"))
        conn.execute(
            sa.text(
                """
                UPDATE rag_documents
                SET embedding_model = COALESCE(NULLIF(embedding_model, ''), 'legacy'),
                    embedding_dimension = COALESCE(embedding_dimension, vector_dims(embedding))
                """
            )
        )
        invalid_rows = conn.execute(
            sa.text(
                """
                SELECT count(*)
                FROM rag_documents
                WHERE embedding IS NULL OR embedding_model IS NULL OR embedding_dimension IS NULL
                """
            )
        ).scalar_one()
        if invalid_rows:
            raise RuntimeError(
                "rag_documents contains vectors that cannot be assigned a model profile; reindex the legacy corpus"
            )
        conn.execute(sa.text("ALTER TABLE rag_documents ALTER COLUMN embedding_model SET NOT NULL"))
        conn.execute(sa.text("ALTER TABLE rag_documents ALTER COLUMN embedding_dimension SET NOT NULL"))
        conn.execute(sa.text("ALTER TABLE rag_documents ALTER COLUMN created_at SET NOT NULL"))
        conn.execute(
            sa.text(
                """
                ALTER TABLE rag_documents
                DROP CONSTRAINT IF EXISTS ck_rag_documents_embedding_dimension
                """
            )
        )
        conn.execute(
            sa.text(
                """
                ALTER TABLE rag_documents
                ADD CONSTRAINT ck_rag_documents_embedding_dimension
                    CHECK (vector_dims(embedding) = embedding_dimension)
                """
            )
        )

    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_rag_documents_doc_type ON rag_documents (doc_type)"))
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_documents_profile
            ON rag_documents (embedding_model, embedding_dimension)
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_embedding_bge_small_384
            ON rag_documents USING hnsw ((embedding::vector(384)) vector_cosine_ops)
            WITH (m = 16, ef_construction = 100)
            WHERE embedding_model = 'BAAI/bge-small-en-v1.5' AND embedding_dimension = 384
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_embedding_text_embedding_3_small_1536
            ON rag_documents USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
            WITH (m = 16, ef_construction = 100)
            WHERE embedding_model = 'text-embedding-3-small' AND embedding_dimension = 1536
            """
        )
    )


def downgrade() -> None:
    """Drop only indexes introduced by this migration; preserve indexed content."""
    conn = op.get_bind()
    if not conn.execute(sa.text("SELECT to_regclass('rag_documents') IS NOT NULL")).scalar():
        return
    op.drop_index("idx_rag_embedding_text_embedding_3_small_1536", table_name="rag_documents", if_exists=True)
    op.drop_index("idx_rag_embedding_bge_small_384", table_name="rag_documents", if_exists=True)
    op.drop_index("idx_rag_documents_profile", table_name="rag_documents", if_exists=True)
