"""
RAG (Retrieval-Augmented Generation) Engine.

Uses Redis Vector Search to store and retrieve:
- CVE descriptions and details
- Previous assessment findings
- Tool documentation and usage patterns
- Security knowledge base
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.commands.search.field import TagField, TextField, VectorField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from redis.exceptions import ResponseError

logger = logging.getLogger("spectra.ai.rag")


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

    # Redis key prefixes
    index_name: str = "spectra:rag:idx"
    doc_prefix: str = "spectra:rag:doc:"

    # Embedding configuration
    embedding_dim: int = 384  # Dimension for sentence-transformers
    embedding_model: str = "all-MiniLM-L6-v2"

    # Search configuration
    default_top_k: int = 5
    min_score: float = 0.5

    # Index configuration
    distance_metric: str = "COSINE"


# --- Embedding Service ---


from app.services.ai.embeddings import EmbeddingService


# --- RAG Service ---


class RAGService:
    """
    Retrieval-Augmented Generation service using Redis Vector Search.

    Provides:
    - Document indexing with vector embeddings
    - Semantic similarity search
    - Hybrid search (vector + keyword)
    - CVE and finding retrieval

    Example:
        rag = RAGService(redis_client)
        await rag.initialize()

        # Index a CVE
        await rag.index_document(Document(
            id="cve-2024-1234",
            content="SQL injection in...",
            doc_type="cve",
            cve_id="CVE-2024-1234",
            severity="critical",
        ))

        # Search
        results = await rag.search("SQL injection vulnerability")
    """

    def __init__(
        self,
        redis: Redis,
        config: RAGConfig | None = None,
    ):
        self.redis = redis
        self.config = config or RAGConfig()
        self.embeddings = EmbeddingService(self.config.embedding_model)
        self._index_exists = False

    async def initialize(self) -> bool:
        """Initialize the RAG index in Redis."""
        try:
            # Check if index exists
            try:
                await self.redis.ft(self.config.index_name).info()
                self._index_exists = True
                logger.info("RAG index '%s' already exists", self.config.index_name)
                return True
            except ResponseError:
                # Index does not exist
                pass
            except Exception as e:
                logger.warning("Error checking RAG index: %s", e)

            # Create index schema
            schema = [
                TextField("content", weight=1.0),
                TextField("doc_type", weight=0.5),
                TagField("cve_id"),
                TagField("severity"),
                TagField("target"),
                TagField("session_id"),
                VectorField(
                    "embedding",
                    "HNSW",
                    {
                        "TYPE": "FLOAT32",
                        "DIM": self.config.embedding_dim,
                        "DISTANCE_METRIC": self.config.distance_metric,
                    },
                ),
            ]

            # Create the index
            await self.redis.ft(self.config.index_name).create_index(
                schema,
                definition=IndexDefinition(
                    prefix=[self.config.doc_prefix],
                    index_type=IndexType.HASH,
                ),
            )

            self._index_exists = True
            logger.info("Created RAG index: %s", self.config.index_name)
            return True

        except Exception as e:
            logger.error("Failed to initialize RAG index: %s", e)
            return False

    async def index_document(self, doc: Document) -> bool:
        """
        Index a document with its embedding.

        Args:
            doc: The document to index.

        Returns:
            True if successful.
        """
        if not self._index_exists:
            await self.initialize()

        try:
            # Generate embedding
            embedding = await self.embeddings.embed(doc.content)

            # Prepare document data
            doc_data = {
                "content": doc.content,
                "doc_type": doc.doc_type,
                "metadata": json.dumps(doc.metadata),
                "embedding": self._vector_to_bytes(embedding),
            }

            # Add optional fields
            if doc.cve_id:
                doc_data["cve_id"] = doc.cve_id
            if doc.severity:
                doc_data["severity"] = doc.severity
            if doc.target:
                doc_data["target"] = doc.target
            if doc.session_id:
                doc_data["session_id"] = doc.session_id

            # Store in Redis
            key = f"{self.config.doc_prefix}{doc.id}"
            await self.redis.hset(key, mapping=doc_data)  # type: ignore[misc]

            logger.debug("Indexed document: %s", doc.id)
            return True

        except Exception as e:
            logger.error("Failed to index document %s: %s", doc.id, e)
            return False

    async def index_batch(self, docs: list[Document]) -> int:
        """
        Index multiple documents efficiently.

        Args:
            docs: List of documents to index.

        Returns:
            Number of successfully indexed documents.
        """
        if not docs:
            return 0

        if not self._index_exists:
            await self.initialize()

        # Generate embeddings in batch
        contents = [doc.content for doc in docs]
        embeddings = await self.embeddings.embed_batch(contents)

        success_count = 0
        pipe = self.redis.pipeline()

        for doc, embedding in zip(docs, embeddings):
            try:
                doc_data = {
                    "content": doc.content,
                    "doc_type": doc.doc_type,
                    "metadata": json.dumps(doc.metadata),
                    "embedding": self._vector_to_bytes(embedding),
                }

                if doc.cve_id:
                    doc_data["cve_id"] = doc.cve_id
                if doc.severity:
                    doc_data["severity"] = doc.severity
                if doc.target:
                    doc_data["target"] = doc.target
                if doc.session_id:
                    doc_data["session_id"] = doc.session_id

                key = f"{self.config.doc_prefix}{doc.id}"
                pipe.hset(key, mapping=doc_data)
                success_count += 1

            except Exception as e:
                logger.warning("Failed to prepare document %s: %s", doc.id, e)

        await pipe.execute()
        logger.info("Indexed %d/%d documents", success_count, len(docs))
        return success_count

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        doc_type: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar documents.

        Args:
            query: Search query text.
            top_k: Number of results to return.
            doc_type: Filter by document type.
            filters: Additional tag filters (e.g., {"severity": "critical"}).

        Returns:
            List of search results sorted by relevance.
        """
        if not self._index_exists:
            await self.initialize()

        top_k = top_k or self.config.default_top_k

        try:
            # Generate query embedding
            query_embedding = await self.embeddings.embed(query)

            # Build filter string
            filter_parts = []
            if doc_type:
                filter_parts.append(f"@doc_type:{doc_type}")
            if filters:
                for field, value in filters.items():
                    filter_parts.append(f"@{field}:{{{value}}}")

            filter_str = " ".join(filter_parts) if filter_parts else "*"

            # Build KNN query
            query_str = f"({filter_str})=>[KNN {top_k} @embedding $vec AS score]"

            q = (
                Query(query_str)
                .return_fields("content", "doc_type", "cve_id", "severity", "target", "session_id", "metadata", "score")
                .sort_by("score")
                .dialect(2)
            )

            # Execute search
            # Note: query_params accepts bytes for vector search despite type hint
            result = await self.redis.ft(self.config.index_name).search(
                q,
                query_params={"vec": self._vector_to_bytes(query_embedding)},  # type: ignore
            )

            # Parse results
            results = []
            for doc in result.docs:  # type: ignore
                try:
                    score = float(doc.score) if hasattr(doc, "score") else 0.0

                    # Convert cosine distance to similarity (1 - distance for cosine)
                    similarity = 1 - score

                    if similarity < self.config.min_score:
                        continue

                    document = Document(
                        id=doc.id.replace(self.config.doc_prefix, ""),
                        content=doc.content,
                        doc_type=doc.doc_type,
                        cve_id=getattr(doc, "cve_id", None),
                        severity=getattr(doc, "severity", None),
                        target=getattr(doc, "target", None),
                        session_id=getattr(doc, "session_id", None),
                        metadata=json.loads(getattr(doc, "metadata", "{}")),
                    )

                    results.append(
                        SearchResult(
                            document=document,
                            score=similarity,
                        )
                    )
                except Exception as e:
                    logger.warning("Failed to parse search result: %s", e)

            return results

        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    async def get_document(self, doc_id: str) -> Document | None:
        """Retrieve a document by ID."""
        key = f"{self.config.doc_prefix}{doc_id}"

        try:
            data = await self.redis.hgetall(key)  # type: ignore
            if not data:
                return None

            return Document(
                id=doc_id,
                content=data.get(b"content", b"").decode(),
                doc_type=data.get(b"doc_type", b"").decode(),
                cve_id=data.get(b"cve_id", b"").decode() or None,
                severity=data.get(b"severity", b"").decode() or None,
                target=data.get(b"target", b"").decode() or None,
                session_id=data.get(b"session_id", b"").decode() or None,
                metadata=json.loads(data.get(b"metadata", b"{}")),
            )
        except Exception as e:
            logger.error("Failed to get document %s: %s", doc_id, e)
            return None

    async def delete_document(self, doc_id: str) -> bool:
        """Delete a document from the index."""
        key = f"{self.config.doc_prefix}{doc_id}"
        result = await self.redis.delete(key)
        return result > 0

    async def get_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        try:
            info = await self.redis.ft(self.config.index_name).info()
            return {
                "num_docs": info.get("num_docs", 0),
                "num_terms": info.get("num_terms", 0),
                "index_name": self.config.index_name,
            }
        except Exception as e:
            return {"error": str(e)}

    def _vector_to_bytes(self, vector: list[float]) -> bytes:
        """Convert float vector to bytes for Redis."""
        import struct

        return struct.pack(f"{len(vector)}f", *vector)

    # --- Convenience Methods ---

    async def search_cves(
        self,
        query: str,
        severity: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Search for CVEs matching a query."""
        filters = {}
        if severity:
            filters["severity"] = severity

        return await self.search(
            query=query,
            top_k=top_k,
            doc_type="cve",
            filters=filters if filters else None,
        )

    async def search_findings(
        self,
        query: str,
        session_id: str | None = None,
        target: str | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Search for previous findings."""
        filters = {}
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
        """
        Get relevant context to augment an LLM prompt.

        Args:
            query: The query or topic.
            max_tokens: Approximate max tokens for context.
            doc_types: Types of documents to include.

        Returns:
            Formatted context string for LLM prompts.
        """
        results = await self.search(query, top_k=10)

        if doc_types:
            results = [r for r in results if r.document.doc_type in doc_types]

        context_parts = []
        current_length = 0
        char_per_token = 4  # Rough estimate

        for result in results:
            content = result.document.content
            content_tokens = len(content) // char_per_token

            if current_length + content_tokens > max_tokens:
                break

            # Format based on document type
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
