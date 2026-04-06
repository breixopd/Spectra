"""
PostgreSQL-backed RAG engine.

Stores document embeddings and metadata in PostgreSQL and performs
similarity ranking in application code.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import async_session_maker
from app.services.ai.embeddings import EmbeddingService

logger = logging.getLogger(__name__)

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
    embedding_dim: int = 0  # 0 = auto-detect from embedding service
    embedding_model: str = ""  # Empty = use settings.EMBEDDING_MODEL

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
    _SAFE_COLUMNS: frozenset[str] = frozenset(FILTER_COLUMNS.values())

    def __init__(self, config: RAGConfig | None = None):
        self.config = config or RAGConfig()
        model = self.config.embedding_model or settings.EMBEDDING_MODEL
        self.embeddings = EmbeddingService(model)
        self._table_ready = False

    @property
    def is_functional(self) -> bool:
        """Return True if embedding API is available."""
        return self.embeddings.is_functional

    async def initialize(self) -> bool:
        """Ensure RAG storage table exists."""
        try:
            dim = self.config.embedding_dim
            if dim == 0:
                await self.embeddings._load_model()
                dim = self.embeddings.embedding_dim or 384
                self.config.embedding_dim = dim
            # Validate dim is a safe integer to prevent SQL injection
            dim = int(dim)
            if not (1 <= dim <= 8192):
                raise ValueError(f"Invalid embedding dimension: {dim}")
            async with async_session_maker() as session:
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await session.execute(
                    text(f"""
                    CREATE TABLE IF NOT EXISTS rag_documents (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        doc_type TEXT NOT NULL,
                        cve_id TEXT NULL,
                        severity TEXT NULL,
                        target TEXT NULL,
                        session_id TEXT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding vector({dim}) NOT NULL,
                        content_hash TEXT NULL,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                )
                await session.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_rag_documents_doc_type ON rag_documents (doc_type)")
                )
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_rag_embedding_hnsw "
                        "ON rag_documents USING hnsw (embedding vector_cosine_ops) "
                        "WITH (m = 16, ef_construction = 100)"
                    )
                )
                await session.commit()

            self._table_ready = True
            # Initialize embedding service (async load)
            await self.embeddings._load_model()
            if self.is_functional:
                model_info = self.embeddings.model_name
                logger.info("RAG initialized: pgvector + %s embeddings", model_info)
            else:
                logger.warning("RAG table ready but embedding API not configured  semantic search disabled")
            return True
        except (OSError, RuntimeError, OperationalError) as e:
            logger.error("Failed to initialize Postgres RAG table: %s", e)
            return False

    MAX_DOCUMENT_SIZE = 500_000  # 500 KB per document

    async def index_document(self, doc: Document) -> bool:
        """Index a document with its embedding."""
        if not self._table_ready:
            await self.initialize()

        if len(doc.content) > self.MAX_DOCUMENT_SIZE:
            logger.warning(
                "Document %s too large (%d chars), truncating to %d",
                doc.id,
                len(doc.content),
                self.MAX_DOCUMENT_SIZE,
            )
            doc = doc.model_copy(update={"content": doc.content[: self.MAX_DOCUMENT_SIZE]})

        if not self.is_functional:
            logger.warning(
                "Embedding API not configured  semantic search will not work. "
                "Storing document %s without usable embeddings.",
                doc.id,
            )

        try:
            content_hash = hashlib.sha256(doc.content.encode()).hexdigest()

            # Check if document exists with same content hash
            async with async_session_maker() as session:
                existing = await session.execute(
                    text("SELECT content_hash FROM rag_documents WHERE id = :id"),
                    {"id": doc.id},
                )
                if existing.scalar() == content_hash:
                    return True  # Content unchanged, skip re-embedding

            embedding = await self.embeddings.embed(doc.content)
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            async with async_session_maker() as session:
                await session.execute(
                    text("""
                        INSERT INTO rag_documents
                            (id, content, doc_type, cve_id, severity, target, session_id, metadata, embedding, content_hash)
                        VALUES
                            (:id, :content, :doc_type, :cve_id, :severity, :target, :session_id,
                             CAST(:metadata AS JSONB), CAST(:embedding AS vector), :content_hash)
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content, doc_type = EXCLUDED.doc_type,
                            cve_id = EXCLUDED.cve_id, severity = EXCLUDED.severity,
                            target = EXCLUDED.target, session_id = EXCLUDED.session_id,
                            metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding,
                            content_hash = EXCLUDED.content_hash
                    """),
                    {
                        "id": doc.id,
                        "content": doc.content,
                        "doc_type": doc.doc_type,
                        "cve_id": doc.cve_id,
                        "severity": doc.severity,
                        "target": doc.target,
                        "session_id": doc.session_id,
                        "metadata": json.dumps(doc.metadata),
                        "embedding": embedding_str,
                        "content_hash": content_hash,
                    },
                )
                await session.commit()
            return True
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to index document %s in Postgres RAG: %s", doc.id, e)
            return False

    async def index_batch(self, docs: list[Document]) -> int:
        """Index multiple documents with batch embedding."""
        if not docs:
            return 0
        if not self._table_ready:
            await self.initialize()

        # Compute content hashes and filter out unchanged documents
        doc_hashes = {}
        for doc in docs:
            if len(doc.content) > self.MAX_DOCUMENT_SIZE:
                doc = doc.model_copy(update={"content": doc.content[: self.MAX_DOCUMENT_SIZE]})
            doc_hashes[doc.id] = hashlib.sha256(doc.content.encode()).hexdigest()

        # Check existing hashes in bulk
        try:
            async with async_session_maker() as session:
                doc_ids = list(doc_hashes.keys())
                rows = (
                    (
                        await session.execute(
                            text("SELECT id, content_hash FROM rag_documents WHERE id = ANY(:ids)"),
                            {"ids": doc_ids},
                        )
                    )
                    .mappings()
                    .all()
                )
                existing_hashes = {r["id"]: r["content_hash"] for r in rows}
        except (OSError, RuntimeError, OperationalError):
            existing_hashes = {}

        # Filter to only docs that changed
        docs_to_index = [doc for doc in docs if doc_hashes.get(doc.id) != existing_hashes.get(doc.id)]
        if not docs_to_index:
            return len(docs)  # All unchanged

        # Batch embed all content at once
        try:
            contents = [
                doc.content[: self.MAX_DOCUMENT_SIZE] if len(doc.content) > self.MAX_DOCUMENT_SIZE else doc.content
                for doc in docs_to_index
            ]
            embeddings = await self.embeddings.embed_batch(contents)
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Batch embedding failed, falling back to sequential: %s", e)
            success = 0
            for doc in docs:
                if await self.index_document(doc):
                    success += 1
            return success

        # Bulk insert
        success = 0
        try:
            async with async_session_maker() as session:
                for doc, embedding in zip(docs_to_index, embeddings, strict=True):
                    content_hash = doc_hashes[doc.id]
                    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                    await session.execute(
                        text("""
                            INSERT INTO rag_documents
                                (id, content, doc_type, cve_id, severity, target, session_id,
                                 metadata, embedding, content_hash)
                            VALUES
                                (:id, :content, :doc_type, :cve_id, :severity, :target, :session_id,
                                 CAST(:metadata AS JSONB), CAST(:embedding AS vector), :content_hash)
                            ON CONFLICT (id) DO UPDATE SET
                                content = EXCLUDED.content, doc_type = EXCLUDED.doc_type,
                                cve_id = EXCLUDED.cve_id, severity = EXCLUDED.severity,
                                target = EXCLUDED.target, session_id = EXCLUDED.session_id,
                                metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding,
                                content_hash = EXCLUDED.content_hash
                        """),
                        {
                            "id": doc.id,
                            "content": doc.content[: self.MAX_DOCUMENT_SIZE]
                            if len(doc.content) > self.MAX_DOCUMENT_SIZE
                            else doc.content,
                            "doc_type": doc.doc_type,
                            "cve_id": doc.cve_id,
                            "severity": doc.severity,
                            "target": doc.target,
                            "session_id": doc.session_id,
                            "metadata": json.dumps(doc.metadata),
                            "embedding": embedding_str,
                            "content_hash": content_hash,
                        },
                    )
                    success += 1
                await session.commit()
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Batch insert failed: %s", e)

        # Count unchanged docs as success too
        return success + (len(docs) - len(docs_to_index))

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

        if not self.is_functional:
            logger.warning("RAG search skipped: embedding API not configured")
            return []

        top_k = top_k or self.config.default_top_k

        try:
            query_embedding = await self.embeddings.embed(query)

            # Build SQL with pre-filtering to avoid fetching ALL documents
            where_clauses: list[str] = []
            params: dict[str, Any] = {}

            if doc_type:
                where_clauses.append("doc_type = :doc_type")
                params["doc_type"] = doc_type

            normalized_filters = {
                self.FILTER_COLUMNS[k]: v for k, v in (filters or {}).items() if k in self.FILTER_COLUMNS
            }
            for i, (field, value) in enumerate(normalized_filters.items()):
                if field not in self._SAFE_COLUMNS:
                    continue
                placeholder = f"filter_{i}"
                where_clauses.append(f"{field} = :{placeholder}")
                params[placeholder] = value

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Native pgvector search — O(log N) with HNSW index
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            extra_where = "AND" if where_clauses else "WHERE"
            sql = f"""
                SELECT id, content, doc_type, cve_id, severity, target, session_id, metadata,
                       1 - (embedding <=> CAST(:q_emb AS vector)) AS similarity
                FROM rag_documents
                {where_sql}
                {extra_where} embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:q_emb AS vector)
                LIMIT :top_k
            """
            params["q_emb"] = embedding_str
            params["top_k"] = top_k

            async with async_session_maker() as session:
                await session.execute(text("SET hnsw.ef_search = 60"))
                rows = (await session.execute(text(sql), params)).mappings().all()

            results: list[SearchResult] = []
            for row in rows:
                similarity = float(row["similarity"])
                if similarity < self.config.min_score:
                    continue
                results.append(
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
            return results
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Postgres RAG search failed: %s", e)
            return []

    async def get_document(self, doc_id: str) -> Document | None:
        """Retrieve a document by ID."""
        if not self._table_ready:
            await self.initialize()

        try:
            async with async_session_maker() as session:
                row = (
                    (
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
                    )
                    .mappings()
                    .first()
                )
            if not row:
                return None

            metadata = row.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}

            return Document(
                id=row["id"],
                content=row["content"],
                doc_type=row["doc_type"],
                cve_id=row.get("cve_id"),
                severity=row.get("severity"),
                target=row.get("target"),
                session_id=row.get("session_id"),
                metadata=metadata or {},
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get document %s from Postgres RAG: %s", doc_id, e)
            return None

    async def delete_document(self, doc_id: str) -> bool:
        """Delete a document from the index."""
        if not self._table_ready:
            await self.initialize()
        try:
            async with async_session_maker() as session:
                result = await session.execute(text("DELETE FROM rag_documents WHERE id = :id"), {"id": doc_id})
                deleted = result.rowcount > 0  # type: ignore[union-attr]
                await session.commit()
                return deleted
        except (OSError, RuntimeError) as e:
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
        except (OSError, RuntimeError) as e:
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
        context = "Relevant Context:\n\n" + "\n\n---\n\n".join(context_parts)
        from app.services.ai.sanitizer import sanitize_for_prompt

        context = sanitize_for_prompt(context, max_length=50000, field_name="rag_context")
        return context
