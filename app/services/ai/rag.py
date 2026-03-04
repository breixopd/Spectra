"""
PostgreSQL-backed RAG engine.

Stores document embeddings and metadata in PostgreSQL and performs
similarity ranking in application code.
"""

import json
import logging
import math
from typing import Any

from pydantic import BaseModel, Field
from dataclasses import dataclass
from sqlalchemy import text

from app.core.database import async_session_maker
from app.services.ai.embeddings import EmbeddingService

logger = logging.getLogger("spectra.ai.rag_postgres")

# --- Models ---

class Document(BaseModel):
    """A document to be stored in the RAG system."""

    id: str = Field(..., description="Unique document ID")
    content: str = Field(..., description="Document text content")
    doc_type: str = Field(..., description="Type: cve, finding, tool_doc, knowledge")
    metadata: dict[str, Any] = Field(default_factory=dict)

    # For CVEs
    cve_id: str | None = Field(None, description="CVE identifier if applicable")
    severity: str | None = Field(None, description="Severity level")

    # For findings
    target: str | None = Field(None, description="Target this relates to")
    session_id: str | None = Field(None, description="Session ID if from a finding")


class SearchResult(BaseModel):
    """A search result from the RAG system."""

    document: Document
    score: float = Field(..., description="Similarity score")
    highlights: list[str] = Field(default_factory=list)


@dataclass
class RAGConfig:
    """Configuration for the RAG engine."""

    # Key prefixes (kept for naming consistency)
    index_name: str = "spectra_rag_idx"
    doc_prefix: str = "spectra:rag:doc:"

    # Embedding configuration
    embedding_dim: int = 384  # Dimension for sentence-transformers
    embedding_model: str = "all-MiniLM-L6-v2"

    # Search configuration
    default_top_k: int = 5
    min_score: float = 0.5

    # Indexing configuration
    batch_size: int = 500

    # Index configuration
    distance_metric: str = "COSINE"



class RAGService:
    """Retrieval-Augmented Generation service backed by PostgreSQL."""

    CHARS_PER_TOKEN = 4
    FILTER_COLUMNS = {
        "cve_id": "cve_id",
        "severity": "severity",
        "target": "target",
        "session_id": "session_id",
        "doc_type": "doc_type",
    }

    def __init__(self, config: RAGConfig | None = None):
        self.config = config or RAGConfig()
        self.embeddings = EmbeddingService(self.config.embedding_model)
        self._table_ready = False

    async def initialize(self) -> bool:
        """Ensure RAG storage table exists."""
        try:
            async with async_session_maker() as session:
                dialect = session.bind.dialect.name

                if dialect == "sqlite":
                    create_sql = """
                        CREATE TABLE IF NOT EXISTS rag_documents (
                            id TEXT PRIMARY KEY,
                            content TEXT NOT NULL,
                            doc_type TEXT NOT NULL,
                            cve_id TEXT NULL,
                            severity TEXT NULL,
                            target TEXT NULL,
                            session_id TEXT NULL,
                            metadata TEXT NOT NULL DEFAULT '{}',
                            embedding TEXT NOT NULL
                        )
                        """
                else:
                    create_sql = """
                        CREATE TABLE IF NOT EXISTS rag_documents (
                            id TEXT PRIMARY KEY,
                            content TEXT NOT NULL,
                            doc_type TEXT NOT NULL,
                            cve_id TEXT NULL,
                            severity TEXT NULL,
                            target TEXT NULL,
                            session_id TEXT NULL,
                            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                            embedding JSONB NOT NULL
                        )
                        """

                await session.execute(text(create_sql))
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_rag_documents_doc_type ON rag_documents (doc_type)"
                    )
                )
                await session.commit()

            self._table_ready = True
            return True
        except Exception as e:
            logger.error("Failed to initialize Postgres RAG table: %s", e)
            return False

    async def index_document(self, doc: Document) -> bool:
        """Index a document with its embedding."""
        if not self._table_ready:
            await self.initialize()

        try:
            embedding = await self.embeddings.embed(doc.content)
            async with async_session_maker() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO rag_documents
                            (id, content, doc_type, cve_id, severity, target, session_id, metadata, embedding)
                        VALUES
                            (:id, :content, :doc_type, :cve_id, :severity, :target, :session_id, CAST(:metadata AS JSONB), CAST(:embedding AS JSONB))
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            doc_type = EXCLUDED.doc_type,
                            cve_id = EXCLUDED.cve_id,
                            severity = EXCLUDED.severity,
                            target = EXCLUDED.target,
                            session_id = EXCLUDED.session_id,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "id": doc.id,
                        "content": doc.content,
                        "doc_type": doc.doc_type,
                        "cve_id": doc.cve_id,
                        "severity": doc.severity,
                        "target": doc.target,
                        "session_id": doc.session_id,
                        "metadata": json.dumps(doc.metadata),
                        "embedding": json.dumps(embedding),
                    },
                )
                await session.commit()
            return True
        except Exception as e:
            logger.error("Failed to index document %s in Postgres RAG: %s", doc.id, e)
            return False

    async def index_batch(self, docs: list[Document]) -> int:
        """Index multiple documents efficiently."""
        if not docs:
            return 0

        if not self._table_ready:
            await self.initialize()

        try:
            async with async_session_maker() as session:
                dialect = session.bind.dialect.name

                records: list[dict[str, Any]] = []
                for doc in docs:
                    # Generate embedding per document to preserve existing behavior.
                    embedding = await self.embeddings.embed(doc.content)

                    metadata_json = json.dumps(getattr(doc, "metadata", {}) or {})
                    embedding_json = json.dumps(embedding)

                    records.append(
                        {
                            "id": doc.id,
                            "content": doc.content,
                            "doc_type": doc.doc_type,
                            "cve_id": getattr(doc, "cve_id", None),
                            "severity": getattr(doc, "severity", None),
                            "target": getattr(doc, "target", None),
                            "session_id": getattr(doc, "session_id", None),
                            "metadata": metadata_json,
                            "embedding": embedding_json,
                        }
                    )

                if not records:
                    return 0

                if dialect == "sqlite":
                    insert_sql = """
                        INSERT INTO rag_documents (
                            id,
                            content,
                            doc_type,
                            cve_id,
                            severity,
                            target,
                            session_id,
                            metadata,
                            embedding
                        )
                        VALUES (
                            :id,
                            :content,
                            :doc_type,
                            :cve_id,
                            :severity,
                            :target,
                            :session_id,
                            :metadata,
                            :embedding
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            content = excluded.content,
                            doc_type = excluded.doc_type,
                            cve_id = excluded.cve_id,
                            severity = excluded.severity,
                            target = excluded.target,
                            session_id = excluded.session_id,
                            metadata = excluded.metadata,
                            embedding = excluded.embedding
                    """
                else:
                    insert_sql = """
                        INSERT INTO rag_documents (
                            id,
                            content,
                            doc_type,
                            cve_id,
                            severity,
                            target,
                            session_id,
                            metadata,
                            embedding
                        )
                        VALUES (
                            :id,
                            :content,
                            :doc_type,
                            :cve_id,
                            :severity,
                            :target,
                            :session_id,
                            CAST(:metadata AS JSONB),
                            CAST(:embedding AS JSONB)
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            doc_type = EXCLUDED.doc_type,
                            cve_id = EXCLUDED.cve_id,
                            severity = EXCLUDED.severity,
                            target = EXCLUDED.target,
                            session_id = EXCLUDED.session_id,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                    """

                await session.execute(text(insert_sql), records)
                await session.commit()

            return len(records)
        except Exception as e:
            logger.error(
                "Failed to index batch of %s documents in Postgres RAG: %s",
                len(docs),
                e,
            )
            return 0

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        doc_type: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        """Search for similar documents using cosine similarity."""
        if not self._table_ready:
            await self.initialize()

        top_k = top_k or self.config.default_top_k

        try:
            query_embedding = await self.embeddings.embed(query)

            async with async_session_maker() as session:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT id, content, doc_type, cve_id, severity, target, session_id, metadata, embedding
                            FROM rag_documents
                            """
                        ),
                    )
                ).mappings().all()

            scored: list[SearchResult] = []
            normalized_filters = {
                self.FILTER_COLUMNS[k]: v
                for k, v in (filters or {}).items()
                if k in self.FILTER_COLUMNS
            }
            for row in rows:
                if doc_type and row.get("doc_type") != doc_type:
                    continue
                if any(row.get(field) != value for field, value in normalized_filters.items()):
                    continue

                embedding = row.get("embedding")
                if not isinstance(embedding, list):
                    continue

                similarity = self._cosine_similarity(query_embedding, embedding)
                if similarity < self.config.min_score:
                    continue

                scored.append(
                    SearchResult(
                        document=Document(
                            id=row["id"],
                            content=row["content"],
                            doc_type=row["doc_type"],
                            cve_id=row.get("cve_id"),
                            severity=row.get("severity"),
                            target=row.get("target"),
                            session_id=row.get("session_id"),
                            metadata=row.get("metadata") or {},
                        ),
                        score=similarity,
                    )
                )

            scored.sort(key=lambda item: item.score, reverse=True)
            return scored[:top_k]
        except Exception as e:
            logger.error("Postgres RAG search failed: %s", e)
            return []

    async def get_document(self, doc_id: str) -> Document | None:
        """Retrieve a document by ID."""
        if not self._table_ready:
            await self.initialize()

        try:
            async with async_session_maker() as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT id, content, doc_type, cve_id, severity, target, session_id, metadata
                            FROM rag_documents
                            WHERE id = :id
                            """
                        ),
                        {"id": doc_id},
                    )
                ).mappings().first()
            if not row:
                return None
            return Document(
                id=row["id"],
                content=row["content"],
                doc_type=row["doc_type"],
                cve_id=row.get("cve_id"),
                severity=row.get("severity"),
                target=row.get("target"),
                session_id=row.get("session_id"),
                metadata=row.get("metadata") or {},
            )
        except Exception as e:
            logger.error("Failed to get document %s from Postgres RAG: %s", doc_id, e)
            return None

    async def delete_document(self, doc_id: str) -> bool:
        """Delete a document from the index."""
        if not self._table_ready:
            await self.initialize()
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    text("DELETE FROM rag_documents WHERE id = :id"), {"id": doc_id}
                )
                deleted = result.rowcount > 0
                await session.commit()
                return deleted
        except Exception as e:
            logger.error("Failed to delete document %s from Postgres RAG: %s", doc_id, e)
            return False

    async def get_stats(self) -> dict[str, Any]:
        """Get basic index statistics."""
        if not self._table_ready:
            await self.initialize()
        try:
            async with async_session_maker() as session:
                count = await session.execute(text("SELECT COUNT(*) FROM rag_documents"))
                return {"num_docs": count.scalar() or 0, "backend": "postgres"}
        except Exception as e:
            logger.error("Failed to get Postgres RAG stats: %s", e)
            return {"num_docs": 0, "backend": "postgres", "error": str(e)}

    async def search_cves(
        self,
        query: str,
        severity: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        filters = {"severity": severity} if severity else None
        return await self.search(query=query, top_k=top_k, doc_type="cve", filters=filters)

    async def search_findings(
        self,
        query: str,
        session_id: str | None = None,
        target: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        filters: dict[str, str] = {}
        if session_id:
            filters["session_id"] = session_id
        if target:
            filters["target"] = target
        return await self.search(
            query=query,
            top_k=top_k,
            doc_type="finding",
            filters=filters if filters else None,
        )

    async def get_context_for_prompt(
        self,
        query: str,
        max_tokens: int = 2000,
        doc_types: list[str] | None = None,
    ) -> str:
        results = await self.search(query, top_k=10)
        if doc_types:
            doc_types_set = set(doc_types)
            results = [r for r in results if r.document.doc_type in doc_types_set]

        context_parts = []
        current_length = 0

        for result in results:
            content = result.document.content
            content_tokens = len(content) // self.CHARS_PER_TOKEN
            if current_length + content_tokens > max_tokens:
                break

            if result.document.doc_type == "cve":
                part = f"[CVE: {result.document.cve_id or 'Unknown'}]\n{content}"
            elif result.document.doc_type == "finding":
                part = f"[Previous Finding - {result.document.severity or 'Unknown'} severity]\n{content}"
            else:
                part = f"[{result.document.doc_type}]\n{content}"

            context_parts.append(part)
            current_length += content_tokens

        if not context_parts:
            return ""
        return "Relevant Context:\n\n" + "\n\n---\n\n".join(context_parts)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
