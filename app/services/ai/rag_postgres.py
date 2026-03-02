"""
PostgreSQL-backed RAG engine.

Stores document embeddings and metadata in PostgreSQL and performs
similarity ranking in application code.
"""

import json
import logging
import math
from typing import Any

from sqlalchemy import text

from app.core.database import async_session_maker
from app.services.ai.embeddings import EmbeddingService
from app.services.ai.rag import Document, RAGConfig, SearchResult

logger = logging.getLogger("spectra.ai.rag_postgres")


class PostgresRAGService:
    """Retrieval-Augmented Generation service backed by PostgreSQL."""

    def __init__(self, config: RAGConfig | None = None):
        self.config = config or RAGConfig()
        self.embeddings = EmbeddingService(self.config.embedding_model)
        self._table_ready = False

    async def initialize(self) -> bool:
        """Ensure RAG storage table exists."""
        try:
            async with async_session_maker() as session:
                await session.execute(
                    text(
                        """
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
                    )
                )
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
        """Index multiple documents."""
        if not docs:
            return 0
        success = 0
        for doc in docs:
            if await self.index_document(doc):
                success += 1
        return success

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

            where = []
            params: dict[str, Any] = {}
            if doc_type:
                where.append("doc_type = :doc_type")
                params["doc_type"] = doc_type
            if filters:
                for idx, (field, value) in enumerate(filters.items()):
                    if field not in {"cve_id", "severity", "target", "session_id", "doc_type"}:
                        continue
                    key = f"f_{idx}"
                    where.append(f"{field} = :{key}")
                    params[key] = value

            where_clause = f"WHERE {' AND '.join(where)}" if where else ""

            async with async_session_maker() as session:
                rows = (
                    await session.execute(
                        text(
                            f"""
                            SELECT id, content, doc_type, cve_id, severity, target, session_id, metadata, embedding
                            FROM rag_documents
                            {where_clause}
                            """
                        ),
                        params,
                    )
                ).mappings().all()

            scored: list[SearchResult] = []
            for row in rows:
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
        async with async_session_maker() as session:
            result = await session.execute(
                text("DELETE FROM rag_documents WHERE id = :id"), {"id": doc_id}
            )
            await session.commit()
        return result.rowcount > 0

    async def get_stats(self) -> dict[str, Any]:
        """Get basic index statistics."""
        if not self._table_ready:
            await self.initialize()
        async with async_session_maker() as session:
            count = await session.execute(text("SELECT COUNT(*) FROM rag_documents"))
        return {"num_docs": count.scalar() or 0, "backend": "postgres"}

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
        char_per_token = 4

        for result in results:
            content = result.document.content
            content_tokens = len(content) // char_per_token
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
