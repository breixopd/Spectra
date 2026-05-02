# Cross-run memory (Spectra)

- **ORM:** `DeclarativeBase` for app models is `spectra_common.orm.base.Base`; Alembic `target_metadata = Base.metadata`; `InfrastructureBase.metadata = Base.metadata`.
- **RAG HTTP contract:** Each hit in `RAGResponse.results` includes `content`, `score`, `metadata`, `doc_type` (monolith `AIGateway.rag_search` fallback matches `spectra_ai` `/api/v1/ai/rag`).
- **RAG processes:** Monolith singleton `get_rag_service()`; AI svc per-request `RAGService()`; scripts `init_script_services()` direct `RAGService()`.
- **Tenant exploit context:** `get_exploit_context(..., user_id=...)` uses split query (tenant exploit rows + global CVE).
- **Alembic backfill:** `z0a1b2c3d4e5` fills `rag_documents.metadata.user_id` from `missions` when `session_id` matches mission id.
