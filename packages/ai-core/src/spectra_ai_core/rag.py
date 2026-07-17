"""
PostgreSQL-backed RAG engine.

Stores document embeddings and metadata in PostgreSQL and performs
similarity ranking in application code.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from spectra_ai_core.db import get_async_session_maker
from spectra_ai_core.embeddings import EmbeddingService

logger = logging.getLogger(__name__)

# --- Models ---


class Document(BaseModel):
    """A document to be stored in the RAG system."""

    id: str = Field(..., description="Unique document ID")
    content: str = Field(..., description="Document text content")
    doc_type: str = Field(..., description="Type: cve, finding, tool_doc, knowledge")
    metadata: dict[str, Any] = Field(default_factory=dict)

    # For CVEs
    cve_id: str | None = None
    severity: str | None = None

    # For findings
    target: str | None = None
    session_id: str | None = None


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


def _validate_vector_dimension(dim: int) -> int:
    """Validate and return a safe integer dimension for vector operations.

    Raises ValueError if out of range.
    """
    dim = int(dim)
    if not 1 <= dim <= 8192:
        raise ValueError(f"Vector dimension must be 1-8192, got {dim}")
    return dim


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
    _REQUIRED_COLUMNS: frozenset[str] = frozenset(
        {
            "id",
            "content",
            "doc_type",
            "cve_id",
            "severity",
            "target",
            "session_id",
            "metadata",
            "embedding",
            "embedding_model",
            "embedding_dimension",
            "content_hash",
            "created_at",
        }
    )
    _INDEXED_PROFILES: dict[tuple[str, int], str] = {
        ("BAAI/bge-small-en-v1.5", 384): "embedding::vector(384)",
        ("text-embedding-3-small", 1536): "embedding::vector(1536)",
    }

    def __init__(self, config: RAGConfig | None = None):
        self.config = config or RAGConfig()
        model = self.config.embedding_model or ""
        self.embeddings = EmbeddingService(model)
        self._table_ready = False

    @property
    def is_functional(self) -> bool:
        """Return True if embedding API is available."""
        return self.embeddings.is_functional

    async def initialize(self) -> bool:
        """Verify the migration-owned RAG schema and load the embedding backend."""
        try:
            async with get_async_session_maker()() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT array_agg(column_name ORDER BY column_name)
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'rag_documents'
                        """
                    )
                )
                columns = set(result.scalar() or [])
                missing_columns = self._REQUIRED_COLUMNS - columns
                if missing_columns:
                    missing = ", ".join(sorted(missing_columns))
                    raise RuntimeError(f"RAG schema is not migrated; missing columns: {missing}")

            await self.embeddings._load_model()
            self._table_ready = True
            if self.is_functional:
                logger.info("RAG initialized with %s embeddings", self.embeddings.active_model_name)
            else:
                logger.warning("RAG schema is ready but embeddings are unavailable; semantic search is disabled")
            return True
        except (OSError, RuntimeError, SQLAlchemyError) as e:
            logger.error("Failed to verify Postgres RAG schema: %s", e)
            return False

    async def _ensure_initialized(self) -> bool:
        """Initialize once and propagate failure to the public operation."""
        return self._table_ready or await self.initialize()

    def _embedding_profile(self, embedding: list[float]) -> tuple[str, int]:
        """Return a validated model/dimension pair for one vector."""
        dimension = _validate_vector_dimension(len(embedding))
        configured_dimension = self.config.embedding_dim
        if configured_dimension and dimension != _validate_vector_dimension(configured_dimension):
            raise ValueError(
                f"Embedding dimension {dimension} does not match configured RAG dimension {configured_dimension}"
            )
        return self.embeddings.active_model_name, dimension

    @classmethod
    def _vector_expression(cls, profile: tuple[str, int]) -> str:
        """Use a profile-specific HNSW expression only where migration provides one."""
        return cls._INDEXED_PROFILES.get(profile, "embedding")

    MAX_DOCUMENT_SIZE = 500_000  # 500 KB per document

    async def index_document(self, doc: Document) -> bool:
        """Index a document with its embedding."""
        if not await self._ensure_initialized():
            return False

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
                "Embedding backend is unavailable; cannot index document %s.",
                doc.id,
            )
            return False

        try:
            content_hash = hashlib.sha256(doc.content.encode()).hexdigest()

            embedding = await self.embeddings.embed_one(doc.content)
            profile = self._embedding_profile(embedding)
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            async with get_async_session_maker()() as session:
                existing = await session.execute(
                    text(
                        """
                        SELECT content_hash, embedding_model, embedding_dimension
                        FROM rag_documents
                        WHERE id = :id
                        """
                    ),
                    {"id": doc.id},
                )
                existing_row = existing.mappings().first()
                if isawaitable(existing_row):
                    existing_row = await existing_row
                if existing_row and (
                    existing_row["content_hash"],
                    existing_row["embedding_model"],
                    existing_row["embedding_dimension"],
                ) == (content_hash, profile[0], profile[1]):
                    return True

                await session.execute(
                    text("""
                        INSERT INTO rag_documents
                            (id, content, doc_type, cve_id, severity, target, session_id, metadata,
                             embedding, embedding_model, embedding_dimension, content_hash)
                        VALUES
                            (:id, :content, :doc_type, :cve_id, :severity, :target, :session_id,
                             CAST(:metadata AS JSONB), CAST(:embedding AS vector), :embedding_model,
                             :embedding_dimension, :content_hash)
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content, doc_type = EXCLUDED.doc_type,
                            cve_id = EXCLUDED.cve_id, severity = EXCLUDED.severity,
                            target = EXCLUDED.target, session_id = EXCLUDED.session_id,
                            metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding,
                            embedding_model = EXCLUDED.embedding_model,
                            embedding_dimension = EXCLUDED.embedding_dimension,
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
                        "embedding_model": profile[0],
                        "embedding_dimension": profile[1],
                        "content_hash": content_hash,
                    },
                )
                await session.commit()
            return True
        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as e:
            logger.error("Failed to index document %s in Postgres RAG: %s", doc.id, e)
            return False

    async def index_batch(self, docs: list[Document]) -> int:
        """Index multiple documents with batch embedding."""
        if not docs:
            return 0
        if not await self._ensure_initialized():
            return 0
        if not self.is_functional:
            logger.warning("Embedding backend is unavailable; cannot index a batch of %d documents", len(docs))
            return 0

        # Compute content hashes and filter out unchanged documents
        doc_hashes = {}
        for doc in docs:
            if len(doc.content) > self.MAX_DOCUMENT_SIZE:
                doc = doc.model_copy(update={"content": doc.content[: self.MAX_DOCUMENT_SIZE]})
            doc_hashes[doc.id] = hashlib.sha256(doc.content.encode()).hexdigest()

        # Check existing hashes in bulk
        try:
            async with get_async_session_maker()() as session:
                doc_ids = list(doc_hashes.keys())
                rows = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT id, content_hash, embedding_model, embedding_dimension
                                FROM rag_documents
                                WHERE id = ANY(:ids)
                                """
                            ),
                            {"ids": doc_ids},
                        )
                    )
                    .mappings()
                    .all()
                )
                existing_hashes = {
                    row["id"]: (row["content_hash"], row["embedding_model"], row["embedding_dimension"]) for row in rows
                }
        except (OSError, RuntimeError, SQLAlchemyError):
            existing_hashes: dict[str, tuple[str | None, str | None, int | None]] = {}

        dimension_hint = self.embeddings.embedding_dim
        profile_hint = (self.embeddings.active_model_name, dimension_hint) if dimension_hint is not None else None
        docs_to_index = [
            doc
            for doc in docs
            if (doc_hashes.get(doc.id), *(profile_hint or (None, None))) != existing_hashes.get(doc.id)
        ]
        if not docs_to_index:
            return len(docs)  # All unchanged

        # Batch embed all content at once
        try:
            contents = [
                doc.content[: self.MAX_DOCUMENT_SIZE] if len(doc.content) > self.MAX_DOCUMENT_SIZE else doc.content
                for doc in docs_to_index
            ]
            embeddings = await self.embeddings.embed(contents)
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
            async with get_async_session_maker()() as session:
                for doc, embedding in zip(docs_to_index, embeddings, strict=True):
                    content_hash = doc_hashes[doc.id]
                    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                    profile = self._embedding_profile(embedding)
                    await session.execute(
                        text("""
                            INSERT INTO rag_documents
                                (id, content, doc_type, cve_id, severity, target, session_id,
                                 metadata, embedding, embedding_model, embedding_dimension, content_hash)
                            VALUES
                                (:id, :content, :doc_type, :cve_id, :severity, :target, :session_id,
                                 CAST(:metadata AS JSONB), CAST(:embedding AS vector), :embedding_model,
                                 :embedding_dimension, :content_hash)
                            ON CONFLICT (id) DO UPDATE SET
                                content = EXCLUDED.content, doc_type = EXCLUDED.doc_type,
                                cve_id = EXCLUDED.cve_id, severity = EXCLUDED.severity,
                                target = EXCLUDED.target, session_id = EXCLUDED.session_id,
                                metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding,
                                embedding_model = EXCLUDED.embedding_model,
                                embedding_dimension = EXCLUDED.embedding_dimension,
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
                            "embedding_model": profile[0],
                            "embedding_dimension": profile[1],
                            "content_hash": content_hash,
                        },
                    )
                    success += 1
                await session.commit()
        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as e:
            logger.error("Batch insert failed: %s", e)

        # Count unchanged docs as success too
        return success + (len(docs) - len(docs_to_index))

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        doc_type: str | None = None,
        doc_types: list[str] | None = None,
        filters: dict[str, str] | None = None,
        user_id: str | None = None,
        exclude_session_id: str | None = None,
    ) -> list[SearchResult]:
        """Search for similar documents using cosine similarity."""
        if not await self._ensure_initialized():
            return []

        if not self.is_functional:
            logger.warning("RAG search skipped: embedding API not configured")
            return []

        want = top_k or self.config.default_top_k
        # Oversample when min_score prunes rows so LIMIT is not applied only to globally top-k neighbors.
        sql_limit = max(want * 6, 48) if self.config.min_score > 0 else want

        try:
            query_embedding = await self.embeddings.embed_one(query)
            profile = self._embedding_profile(query_embedding)
            vector_expression = self._vector_expression(profile)
            vector_type = f"vector({profile[1]})" if vector_expression != "embedding" else "vector"

            # Build SQL with pre-filtering to avoid fetching ALL documents
            where_clauses: list[str] = [
                "embedding_model = :rag_embedding_model",
                "embedding_dimension = :rag_embedding_dimension",
            ]
            params: dict[str, Any] = {
                "rag_embedding_model": profile[0],
                "rag_embedding_dimension": profile[1],
            }

            effective_types = doc_types if doc_types else None
            if effective_types:
                placeholders = ", ".join(f":dt_{i}" for i in range(len(effective_types)))
                where_clauses.append(f"doc_type IN ({placeholders})")
                for i, dt in enumerate(effective_types):
                    params[f"dt_{i}"] = dt
            elif doc_type:
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

            if user_id:
                where_clauses.append("(metadata->>'user_id') = :rag_user_id")
                params["rag_user_id"] = user_id

            if exclude_session_id:
                where_clauses.append("(session_id IS NULL OR session_id <> :rag_exclude_session)")
                params["rag_exclude_session"] = exclude_session_id

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Native pgvector search. Built-in profiles use a migration-owned
            # HNSW expression index; custom profiles preserve exact recall.
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            extra_where = "AND" if where_clauses else "WHERE"
            sql = f"""
                SELECT id, content, doc_type, cve_id, severity, target, session_id, metadata,
                       1 - ({vector_expression} <=> CAST(:q_emb AS {vector_type})) AS similarity
                FROM rag_documents
                {where_sql}
                {extra_where} embedding IS NOT NULL
                ORDER BY {vector_expression} <=> CAST(:q_emb AS {vector_type})
                LIMIT :sql_limit
            """
            params["q_emb"] = embedding_str
            params["sql_limit"] = sql_limit

            async with get_async_session_maker()() as session:
                if vector_expression != "embedding":
                    await session.execute(text("SET LOCAL hnsw.ef_search = 60"))
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
                if len(results) >= want:
                    break
            return results
        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as e:
            logger.error("Postgres RAG search failed: %s", e)
            return []

    async def get_document(self, doc_id: str) -> Document | None:
        """Retrieve a document by ID."""
        if not await self._ensure_initialized():
            return None

        try:
            async with get_async_session_maker()() as session:
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
        except (OSError, RuntimeError, SQLAlchemyError) as e:
            logger.error("Failed to get document %s from Postgres RAG: %s", doc_id, e)
            return None

    async def delete_document(self, doc_id: str) -> bool:
        """Delete a document from the index."""
        if not await self._ensure_initialized():
            return False
        try:
            async with get_async_session_maker()() as session:
                result = await session.execute(text("DELETE FROM rag_documents WHERE id = :id"), {"id": doc_id})
                deleted = result.rowcount > 0  # type: ignore[union-attr]
                await session.commit()
                return deleted
        except (OSError, RuntimeError, SQLAlchemyError) as e:
            logger.error("Failed to delete document %s from Postgres RAG: %s", doc_id, e)
            return False

    async def get_stats(self) -> dict[str, Any]:
        """Get basic index statistics."""
        if not await self._ensure_initialized():
            return {"num_docs": 0, "backend": "postgres", "error": "RAG schema is unavailable"}
        try:
            async with get_async_session_maker()() as session:
                count = await session.execute(text("SELECT COUNT(*) FROM rag_documents"))
                return {"num_docs": count.scalar() or 0, "backend": "postgres"}
        except (OSError, RuntimeError, SQLAlchemyError) as e:
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
        user_id: str | None = None,
        exclude_session_id: str | None = None,
    ) -> str:
        results = await self.search(
            query,
            top_k=10,
            doc_types=doc_types,
            user_id=user_id,
            exclude_session_id=exclude_session_id,
        )

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
        from spectra_ai_core.sanitizer import sanitize_for_prompt

        context = sanitize_for_prompt(context, max_length=50000, field_name="rag_context")
        return context
