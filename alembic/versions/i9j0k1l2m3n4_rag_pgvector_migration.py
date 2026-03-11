"""RAG pgvector migration - require pgvector, migrate embedding column

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-08

NOTE: rag_documents table is created at runtime by RAGService.initialize(),
not via Alembic. This migration enables pgvector extension (required) and
migrates any existing JSONB embedding column to vector(1536).
"""

# pyright: reportAttributeAccessIssue=false
# ruff: noqa: I001

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Check if pgvector is available on this PostgreSQL installation
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
    ))
    pgvector_available = result.first() is not None

    if not pgvector_available:
        return

    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # Only migrate rag_documents if it already exists (created at runtime by RAGService)
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'rag_documents'"
    ))
    if not result.first():
        # Table doesn't exist yet — RAGService.initialize() will create it with
        # the correct schema (vector column, HNSW index) on first use
        return

    # Check if embedding column needs migration from JSONB to vector
    result = conn.execute(sa.text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'rag_documents' AND column_name = 'embedding'"
    ))
    row = result.first()
    if row and row[1] != 'USER-DEFINED':  # Not already vector type
        conn.execute(sa.text("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS embedding_new vector(1536)"))
        conn.execute(sa.text(
            "UPDATE rag_documents SET embedding_new = embedding::vector(1536) "
            "WHERE embedding IS NOT NULL AND jsonb_array_length(embedding) = 1536"
        ))
        conn.execute(sa.text("ALTER TABLE rag_documents DROP COLUMN embedding"))
        conn.execute(sa.text("ALTER TABLE rag_documents RENAME COLUMN embedding_new TO embedding"))

    # Add created_at if missing
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'rag_documents' AND column_name = 'created_at'"
    ))
    if not result.first():
        conn.execute(sa.text(
            "ALTER TABLE rag_documents ADD COLUMN created_at TIMESTAMPTZ DEFAULT now()"
        ))

    # HNSW index for fast similarity search
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_rag_embedding_hnsw "
        "ON rag_documents USING hnsw (embedding vector_cosine_ops)"
    ))


def downgrade() -> None:
    # pgvector extension is shared infrastructure — don't drop it
    conn = op.get_bind()

    # Only downgrade if the table exists
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'rag_documents'"
    ))
    if not result.first():
        return

    # Drop HNSW index
    op.drop_index('idx_rag_embedding_hnsw', table_name='rag_documents', if_exists=True)

    # Convert vector(1536) back to JSONB
    result = conn.execute(sa.text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'rag_documents' AND column_name = 'embedding'"
    ))
    row = result.first()
    if row and row[0] == 'USER-DEFINED':  # vector type
        op.alter_column('rag_documents', 'embedding',
            type_=postgresql.JSONB,
            postgresql_using='embedding::text::jsonb')

    # Drop created_at column
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'rag_documents' AND column_name = 'created_at'"
    ))
    if result.first():
        op.drop_column('rag_documents', 'created_at')
