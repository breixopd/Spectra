# Microservices Architecture

[← Wiki Home](home.md) | [Deployment Guide](deployment-guide.md) | [Sandboxes](sandboxes.md) | [Scaling](scaling.md)

---

## Current Architecture

Spectra runs as four independently deployable services sharing a PostgreSQL database. All services use the same codebase (`spectra-app` image) with different entry points.

### Implemented Services

| Service | Entry Point | Port | Purpose | Status |
|---------|-------------|------|---------|--------|
| **App (Core API)** | `scripts/start.sh` | 5000 | Web UI, REST API, mission orchestration | **Done** |
| **AI Service** | `app.ai_service:app` | 5010 | LLM routing, embeddings, RAG queries | **Done** |
| **Scheduler** | `app.scheduler_service:app` | 5011 | Background tasks, backups, sandbox watchdog, metrics | **Done** |
| **Worker** | `app.worker_service:app` | 5012 | Tool execution from PG job queue | **Done** |

Supporting infrastructure:

| Service | Image | Purpose |
|---------|-------|---------|
| **PostgreSQL** | `pgvector/pgvector:pg16` | Data store, cache, job queue, pub/sub, RAG vectors |
| **Caddy** | `caddy:2-alpine` | Reverse proxy, TLS termination, security headers |
| **MinIO** | `minio/minio` | S3-compatible object storage (optional) |

### Running

All services run as microservices by default:

```bash
docker compose -f docker/docker-compose.yml up -d
```

The main compose file includes `app`, `ai-svc`, `scheduler`, and `worker` as separate containers.

---

## Service Details

### App (Core API) — `spectra-app`

The main service handling all user-facing functionality.

| Attribute | Value |
|-----------|-------|
| **Source** | `app/main.py` (full monolith) or `SERVICE_MODE=api` (API-only) |
| **Port** | 5000 |
| **Responsibilities** | Web UI, REST API, mission orchestration, user management, admin panel |
| **Dependencies** | PostgreSQL, AI Service (when `AI_SERVICE_URL` is set) |

When `AI_SERVICE_URL` is set, AI requests are proxied to the AI service instead of being handled in-process.

### AI Service — `spectra-ai-svc`

Dedicated LLM routing, embedding generation, and RAG queries.

| Attribute | Value |
|-----------|-------|
| **Source** | `app/ai_service.py` |
| **Port** | 5010 |
| **API Surface** | `POST /api/v1/ai/chat`, `POST /api/v1/ai/embed`, `GET /health` |
| **Dependencies** | PostgreSQL (pgvector for RAG), LLM provider (configurable) |
| **Resource Limits** | 1 CPU, 1 GB RAM (configurable) |

Uses the `SmartRouter` (`app/services/ai/router.py`) with TensorZero for provider-agnostic model routing across tiers.

### Scheduler — `spectra-scheduler`

Headless background task runner.

| Attribute | Value |
|-----------|-------|
| **Source** | `app/scheduler_service.py` |
| **Port** | 5011 (health endpoint only) |
| **Responsibilities** | Sandbox watchdog (cleanup stale containers), warm pool maintenance, quota resets, metrics aggregation, automated backups |
| **Dependencies** | PostgreSQL, Docker socket (for container cleanup) |
| **Resource Limits** | 0.5 CPU, 256 MB RAM |

### Worker — `spectra-worker`

Executes tool jobs from the PostgreSQL job queue.

| Attribute | Value |
|-----------|-------|
| **Source** | `app/worker_service.py` |
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

The `ServiceAuthMiddleware` (`app/core/service_auth.py`) validates the `X-Service-Auth` header on incoming requests.

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

Events map to the `EventType` enum in `app/core/events.py`:

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

The `ServiceRegistry` (`app/services/gateway/service_registry.py`) manages this routing transparently. The `GatewayClient` base class (`app/services/gateway/http_client.py`) provides retry with exponential backoff, connection pooling, and bearer-token auth.

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
docker compose -f docker/docker-compose.yml up -d
```

### Multi-Server (Docker Swarm)

```bash
docker stack deploy -c docker/docker-compose.swarm.yml spectra
```

See [Deployment Guide](deployment-guide.md) for full instructions.

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
