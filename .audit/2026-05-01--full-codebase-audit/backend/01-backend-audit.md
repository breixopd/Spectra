# Backend audit (read-only) — 2026-05-01

## Scope

`spectra_platform/services`, AI gateway + mission/RAG call sites, scheduler/worker ties to `app` and `spectra_ai`, `spectra_common.orm.Base`, and RAG singleton vs per-request usage.

## RAG: `get_rag_service()` vs `RAGService()`

**Pattern (intentional):** Monolith holds one initialized instance via `get_rag_service()` (`spectra_platform/services/ai/knowledge.py:26-31`). The AI HTTP service uses a **new** `RAGService()` per RAG request (`services/ai/src/spectra_ai/main.py:264-265`) and for readiness probe (`services/ai/src/spectra_ai/main.py:156-157`). Scripts intentionally bypass the singleton (`scripts/__init__.py:6-11`, `scripts/__init__.py:24-25`).

**Monolith singleton call sites (sample):** `spectra_platform/services/gateway/ai_gateway.py:69-71`, `spectra_platform/services/gateway/ai_gateway.py:96-98`, `spectra_platform/services/mission/manager/checkpoint.py:68-72`, `spectra_platform/services/rag/service.py:12-22`, `spectra_platform/services/ai/agents/exploit_crafter.py:296-299`. No stray `RAGService()` in runtime `spectra_platform/` besides `knowledge.py:30` (singleton construction).

## Confirmed issues (file:line)

1. ~~**Inconsistent RAG hit shape (remote vs monolith fallback):**~~ **Resolved (2026-05-01 audit):** Both paths now return `content`, `score`, `metadata`, `doc_type` (`spectra_platform/services/gateway/ai_gateway.py`, `services/ai/src/spectra_ai/main.py`).

2. ~~**AI `/health` may not receive `Response`:**~~ **Resolved:** handler uses typed `response: Response` and always sets status on degradation (`services/ai/src/spectra_ai/main.py`).

3. **`ServerNode` PK overrides shared `Base` UUID `id`:** Class subclasses `spectra_common.orm.base.Base` but declares integer autoincrement `id` (`spectra_platform/models/server_node.py:17-27`), shadowing `spectra_common.orm.base.Base:26-30`. Works as override but diverges from every other `Base` model’s UUID PK convention.

## `spectra_common.orm.Base`

ORM models and Alembic target the shared declarative base (`spectra_platform/repositories/base.py:16`, `alembic/env.py:47`, `spectra_platform/models/__init__.py:12`). Infrastructure models use `InfrastructureBase` with `metadata = Base.metadata` (`spectra_platform/models/infrastructure.py:12-19`) so one migration registry — good.

## Gateway & mission

`AIGateway` routes to `AI_SERVICE_URL` when set (`spectra_platform/services/gateway/ai_gateway.py:22-29`); otherwise RAG/embed/chat fall back to in-process paths. Mission checkpoint RAG indexing uses `get_rag_service` + `get_rag_facade` (`spectra_platform/services/mission/manager/checkpoint.py:68-76`).

## Scheduler / worker integration

Scheduler FastAPI app imports monolith modules (`app.services.scaling.pool_manager`, `app.core.database`, `app.auth.rate_limit`) — `services/scheduler/src/spectra_scheduler/routes.py:13-21`, `services/scheduler/src/spectra_scheduler/routes.py:32-36`, `services/scheduler/src/spectra_scheduler/routes.py:84-86`. Worker report jobs call `spectra_ai.llm` directly (`services/worker/src/spectra_worker/report_jobs.py:24`, `services/worker/src/spectra_worker/report_jobs.py:60`), parallel to gateway-based AI routes.

## Note

`spectra_platform/services/scheduler/__init__.py` is empty (placeholder).
