# Microservices Architecture

[← Wiki Home](Home.md) | [Deployment Guide](deployment-guide.md) | [Sandboxes](sandboxes.md) | [Scaling](scaling.md)

---

## Current Architecture

Spectra runs as four independently deployable services sharing a PostgreSQL database. Each service has its own Docker build target and per-service requirements file, sharing the same codebase but deployed independently. The `SERVICE_MODE` environment variable is set on **every** image (see Dockerfiles) so shared code in `app.core.config` (for example DB pool sizing) can branch. **Router mounting** for the public Core API is implemented only in `spectra_api.routing.include_routers` and applies only to the **API** container (`spectra_api.main:app`).

### Core API router policy (`spectra_api` only)

The AI, worker, and scheduler processes use **separate** FastAPI applications (`spectra_ai.main`, `spectra_worker`, `spectra_scheduler`); they do **not** load `include_routers`. For `spectra_api`, only these values select the full router surface:

| Mode | Value | Description |
|------|-------|-------------|
| **API** | `api` | Core API + auth + pages + WebSocket (default in `Dockerfile.api`) |
| **ALL** | `all` | Same full surface — local / single-node / integration runners |
| **(empty)** | `""` | Treated like full API for compatibility |

Any other value for this process is **misconfiguration**: only health routes are mounted (fail closed).

### Implemented Services

| Service | Entry Point | Port | Image Size | Purpose | Status |
|---------|-------------|------|------------|---------|--------|
| **App (Core API)** | `scripts/start.sh` | 5000 | ~1.34 GB | Web UI, REST API, mission orchestration | **Done** |
| **AI Service** | `spectra_ai.main:app` | 5010 | ~1.13 GB | LLM routing, embeddings, RAG queries | **Done** |
| **Scheduler** | `spectra_scheduler.main:app` | 5011 | ~558 MB | Background tasks, backups, sandbox watchdog, metrics | **Done** |
| **Worker** | `spectra_worker.main:app` | 5012 | ~4.13 GB | Tool execution from PG job queue | **Done** |

Supporting infrastructure:

| Service | Image | Purpose |
|---------|-------|---------|
| **PostgreSQL** | `pgvector/pgvector:pg16` | Data store, cache, job queue, pub/sub, RAG vectors |
| **Caddy** | `caddy:2-alpine` | Reverse proxy, TLS termination, security headers |
| **Garage** | `dxflrs/garage:v2.2.0` | S3-compatible object storage |
| **TensorZero** | `tensorzero/gateway` | AI gateway — provider-agnostic model routing, observability, optimization |
| **ClickHouse** | `clickhouse/clickhouse-server:24.11-alpine` | Analytics and inference storage for TensorZero |
| **Redis** | `redis:7-alpine` | Shared distributed rate-limiting backend |

### Per-Service Dockerfiles

Production services use dedicated Dockerfiles with per-service dependency files:

```text
deploy/docker/Dockerfile.api        → installs requirements/app.txt, runs spectra_api.main:app
deploy/docker/Dockerfile.ai         → installs requirements/ai.txt, runs spectra_ai.main:app
deploy/docker/Dockerfile.scheduler  → installs requirements/scheduler.txt, runs spectra_scheduler.main:app
deploy/docker/Dockerfile.worker     → installs requirements/worker.txt, runs spectra_worker.main:app
```

Build a specific service image:

```bash
docker build -f deploy/docker/Dockerfile.api -t spectra-api:local .
docker build -f deploy/docker/Dockerfile.ai -t spectra-ai:local .
docker build -f deploy/docker/Dockerfile.scheduler -t spectra-scheduler:local .
docker build -f deploy/docker/Dockerfile.worker -t spectra-worker:local .
```

### Per-Service Requirements Files

Each service has its own requirements file with only the dependencies it needs:

| File | Service | Key Deps |
|------|---------|----------|
| `requirements/app.txt` | API (app) | Full stack — FastAPI, Jinja2, WeasyPrint, all services |
| `requirements/ai.txt` | AI Service | LLM providers, embeddings, RAG, fastembed |
| `requirements/scheduler.txt` | Scheduler | Minimal — DB, HTTP client, scheduling |
| `requirements/worker.txt` | Worker | Tool execution, Docker SDK, parsing |
| `requirements/base.txt` | Shared | Core deps included by all service files |

### Import Boundary Enforcement

Shared packages (`packages/platform/src/spectra_platform/core/`, `packages/platform/src/spectra_platform/models/`) must not import service-specific code. This is enforced by `scripts/check_import_boundaries.py`:

```bash
python3 scripts/check_import_boundaries.py
```

Forbidden top-level imports in shared packages:
- `spectra_api.api.*`
- `spectra_worker.*`
- `spectra_ai.*`
- `spectra_scheduler.*`
- `spectra_worker.__main__`

Lazy imports inside functions are allowed. This keeps the dependency direction clean: services depend on shared code, never the reverse.

### Running

All services run as microservices by default:

```bash
docker compose -f deploy/docker/compose.yaml up -d
```

The main compose file includes `app`, `ai-svc`, `scheduler`, and `worker` as separate containers, each with `SERVICE_MODE` set in their environment.

---

## Service Details

### App (Core API) — `spectra-app`

The main service handling all user-facing functionality.

| Attribute | Value |
|-----------|-------|
| **Source** | `services/api/src/spectra_api/` + `SERVICE_MODE=api` (`spectra_api.main:app`) |
| **Dockerfile** | `deploy/docker/Dockerfile.api` |
| **Requirements** | `requirements/app.txt` |
| **Port** | 5000 |
| **Responsibilities** | Web UI, REST API, mission orchestration, user management, admin panel |
| **Dependencies** | PostgreSQL, AI Service (when `AI_SERVICE_URL` is set) |

When `AI_SERVICE_URL` is set, AI requests are proxied to the AI service instead of being handled in-process.

### AI Service — `spectra-ai-svc`

Dedicated LLM routing, embedding generation, and RAG queries.

| Attribute | Value |
|-----------|-------|
| **Source** | `services/ai/src/spectra_ai/main.py` (implementation still under `spectra_platform/services/ai/`) |
| **Dockerfile** | `deploy/docker/Dockerfile.ai` |
| **Requirements** | `requirements/ai.txt` |
| **Port** | 5010 |
| **API Surface** | `POST /api/v1/ai/chat`, `POST /api/v1/ai/embeddings`, `POST /api/v1/ai/rag`, `GET /health` |
| **Dependencies** | PostgreSQL (pgvector for RAG), LLM provider (configurable) |
| **Resource Limits** | 1 CPU, 1 GB RAM (configurable) |

Uses the `SmartRouter` (`spectra_platform/services/ai/router.py`) with TensorZero for provider-agnostic model routing across tiers.

### Scheduler — `spectra-scheduler`

Headless background task runner.

| Attribute | Value |
|-----------|-------|
| **Source** | `services/scheduler/src/spectra_scheduler/main.py` (implementation still under `spectra_platform/services/**`) |
| **Dockerfile** | `deploy/docker/Dockerfile.scheduler` |
| **Requirements** | `requirements/scheduler.txt` |
| **Port** | 5011 (health endpoint only) |
| **Responsibilities** | Sandbox watchdog (cleanup stale containers), warm pool maintenance, quota resets, metrics aggregation, automated backups |
| **Dependencies** | PostgreSQL, Docker socket (for container cleanup) |
| **Resource Limits** | 0.5 CPU, 256 MB RAM |

### Worker — `spectra-worker`

Executes tool jobs from the PostgreSQL job queue.

| Attribute | Value |
|-----------|-------|
| **Source** | `services/worker/src/spectra_worker/` |
| **Dockerfile** | `deploy/docker/Dockerfile.worker` |
| **Requirements** | `requirements/worker.txt` |
| **Port** | 5012 (health endpoint only) |
| **Responsibilities** | Pull jobs from PG queue, execute security tools in sandbox containers, parse output, write results |
| **Dependencies** | PostgreSQL, Docker socket (for sandbox container management) |
| **Resource Limits** | 1 CPU, 2 GB RAM |
| **Scalable** | Yes — multiple workers can run concurrently |

Workers use `SELECT ... FOR UPDATE SKIP LOCKED` on the job queue, so multiple instances naturally distribute work without conflicts.

---

## Inter-Service Communication

### 1. HTTP + Service Auth

Direct service-to-service calls use HTTP with a shared secret for authentication:

```python
# Requests include X-Service-Auth header
# Verified by ServiceAuthMiddleware on each service
```

Configuration:

```bash
SERVICE_AUTH_SECRET=<shared-secret>   # Same value on all services
AI_SERVICE_URL=http://ai-svc:5010    # Core API → AI Service
```

The `ServiceAuthMiddleware` (`spectra_platform/core/service_auth.py`) validates the `X-Service-Auth` header on incoming requests.

### 2. PostgreSQL Job Queue

The worker service consumes jobs from the `job_queue` table using `LISTEN`/`NOTIFY` for real-time notification and `SELECT ... FOR UPDATE SKIP LOCKED` for safe concurrent processing:

```sql
-- Worker claims a job:
SELECT * FROM job_queue
WHERE status = 'pending'
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Job channels are per-mission: `spectra_jobs_mission_{id}`.

### 3. PostgreSQL NOTIFY/LISTEN (Pub/Sub)

Cross-service events use PostgreSQL's built-in pub/sub — no external message broker needed:

```python
# Publishing an event:
await session.execute(
    text("SELECT pg_notify(:channel, :payload)"),
    {"channel": "spectra_events", "payload": json.dumps(event)},
)

# Subscribing to events:
conn = await asyncpg.connect(dsn)
await conn.add_listener("spectra_events", handle_event)
```

### Event Types

Events map to the `EventType` enum in `spectra_platform/core/events.py`:

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `mission_created` | Core API | Worker (start processing) |
| `mission_completed` | Core API | Scheduler (cleanup) |
| `tool_execution_completed` | Worker | Core API (process results) |
| `sandbox_created` | Worker | Core API (update status) |
| `sandbox_destroyed` | Scheduler | Core API (update status) |

---

## Service Discovery

In Docker Compose, services resolve by container name. Configuration uses environment variables:

```bash
# .env for microservices mode
AI_SERVICE_URL=http://ai-svc:5010
SERVICE_AUTH_SECRET=<shared-secret>

# Optional: read replica for AI service
DATABASE_REPLICA_URL=postgresql+asyncpg://spectra:pass@db-replica:5432/spectra
```

In Docker Swarm, service names resolve via the overlay network DNS. The `docker-compose.swarm.yml` uses the same env var pattern.

---

## Gateway Pattern

The codebase uses a gateway pattern for service abstraction. When a service URL is set, requests go over HTTP; when unset, the in-process implementation is used.

### Existing Gateways

| Gateway | URL Variable | Fallback |
|---------|-------------|----------|
| LLM | `LLM_GATEWAY_URL` | In-process `SmartRouter` |
| Sandbox Orchestrator | `SANDBOX_ORCHESTRATOR_URL` | In-process `SandboxPool` |
| AI Service | `AI_SERVICE_URL` | In-process AI handlers |

The `ServiceRegistry` (`spectra_platform/services/gateway/service_registry.py`) manages this routing transparently. The `GatewayClient` base class (`spectra_platform/services/gateway/http_client.py`) provides retry with exponential backoff, connection pooling, and bearer-token auth.

---

## Health Endpoints

Every service exposes a `GET /health` endpoint:

| Service | URL | Response |
|---------|-----|----------|
| App | `http://app:5000/api/health` | `{"status": "healthy", "components": {"database": {...}}}` |
| AI Service | `http://ai-svc:5010/health` | `{"status": "healthy", "service": "ai"}` |
| Scheduler | `http://scheduler:5011/health` | `{"status": "healthy", "service": "scheduler"}` |
| Worker | `http://worker:5012/health` | `{"status": "healthy", "service": "worker"}` |

Docker Compose health checks poll these endpoints to determine container readiness.

---

## Deployment Options

### Single Server (Docker Compose)

```bash
# All services (microservices by default):
docker compose -f deploy/docker/compose.yaml up -d
```

### Multi-Server (Docker Swarm)

```bash
docker stack deploy -c deploy/docker/docker-compose.swarm.yml spectra
```

See [Deployment Guide](deployment-guide.md) for full instructions. See [Topology](topology.md) for visual architecture diagrams.

---

## Auto-Scaling

The scheduler includes a reactive auto-scaling engine that adjusts service replica counts based on queue depth and utilization metrics. Auto-scaling defaults **on** (`AUTOSCALE_ENABLED=true` in `Settings`); set `AUTOSCALE_ENABLED=false` only as an emergency override. It works with both Docker Compose and Docker Swarm. API, worker, and AI containers also start a lightweight **embedded ops** loop (disk metrics and optional Docker prune when the socket is mounted); full DB/heal/image loops remain scheduler-owned.

See [Scaling](scaling.md#auto-scaling) for full configuration and policy details.

---

## Communication Patterns Summary

| Pattern | Used For | Mechanism |
|---------|----------|-----------|
| **Request/Response** | API calls, AI chat, embeddings | HTTP + `X-Service-Auth` header |
| **Job Queue** | Tool execution, notifications, reports | PostgreSQL `job_queue` + `SELECT ... FOR UPDATE SKIP LOCKED` |
| **Pub/Sub** | Cross-service events (mission lifecycle, sandbox events) | PostgreSQL `NOTIFY`/`LISTEN` |
| **Health Polling** | Readiness, liveness, capacity monitoring | HTTP `GET /health` endpoints |
| **Advisory Locks** | Scheduler leader election, task deduplication | PostgreSQL `pg_try_advisory_lock` |
| **Rate-Limit Counters** | Distributed rate limiting across replicas | Redis |
| **TLS** | Service-to-service HTTP on untrusted networks | Use **https://** URLs for `AI_SERVICE_URL`, `WORKER_SERVICE_URL`, `SCHEDULER_SERVICE_URL`, etc.; terminate TLS at the edge (e.g. Caddy) or mesh. `X-Service-Auth` is a shared secret — treat transport as untrusted without TLS. |

No external message broker is required — PostgreSQL handles queueing, pub/sub, and coordination.

---

## Build plane / image registry (roadmap)

Golden-image builds and worker image promotion (`spectra_platform/services/tools/sandbox/golden_image.py`, worker/orchestrator paths) can become **CPU- and disk-heavy** and may need a **dedicated host** or service: isolated build VMs, a private container registry, and signed promotion into the runtime cluster. That is **not** a separate shipped service today; when you split it out, wire it the same way as other gateways (URL env + `GatewayClient`-style client), keep **registry auth** (token or mTLS) distinct from `SERVICE_AUTH_SECRET`, and restrict network paths so only the worker/orchestrator can pull promoted images.

---

## Future Phases

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 0** | Gateway-ready interfaces (`ServiceRegistry`, `GatewayClient`) | **Done** |
| **Phase 1** | Entry point split — AI Service, Scheduler, Worker | **Done** |
| **Phase 2** | Extract Billing & Reporting as standalone services | Planned |
| **Phase 3** | Extract Sandbox Orchestrator as standalone service | Planned (gateway pattern already in place) |
| **Phase 4** | Split Auth from Core API | Planned |

Each future phase follows the same pattern: define a `Protocol` interface, implement a `GatewayClient`, gate on a URL env var, and fall back to in-process when unset.
