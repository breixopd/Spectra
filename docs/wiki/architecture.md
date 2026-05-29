# Architecture

[← Wiki Home](Home.md) | [Configuration](configuration.md) | [Deployment Guide](deployment-guide.md) | [Plugins](plugins.md)

---

Technical deep-dive into Spectra's agent system, execution pipeline, and learning mechanisms.

## Repository layout

| Area | Role |
|------|------|
| **`packages/platform/src/spectra_platform/`** | Shared domain kernel (workspace package **`spectra-platform`**): ORM models, repositories, mission/tool/AI business logic, infrastructure helpers. Imported in Python as **`spectra_platform`**. |
| **`services/*/src/`** | Deployable edges: `spectra_api` (HTTP), `spectra_worker`, `spectra_scheduler`, `spectra_ai` with thin wiring into `spectra_platform`. |
| **`packages/{common,domain,tools-core}/src/`** | Portable libraries (`spectra_common`, `spectra_domain`, `spectra_tools_core`) with strict import boundaries. |

In containers, `WORKDIR` is `/app`; the platform tree is copied to **`/app/spectra_platform/`** (import path unchanged).

### `packages/platform` vs the smaller `packages/*` libraries

**`spectra-common`**, **`spectra-domain`**, and **`spectra-tools-core`** stay small and dependency-light where possible.

**`spectra-platform`** is the large shared kernel (ORM, Alembic targets, multi-service imports). It lives under **`packages/platform/`** so every first-party Python tree is a **workspace member** with a single `pyproject.toml` pattern (`src/<package>/`). Runtime layout in images remains **`/app/spectra_platform/`** for a short, stable `PYTHONPATH`.

### Other top-level directories

| Path | Role |
|------|------|
| **`alembic/`** | Database migrations for platform models. |
| **`config/`** | Reference or sample configuration (not secrets). |
| **`data/`** | **Gitignored** on the host when present — optional local bind-mount target (e.g. encryption keys, caches). Prefer **`docker/data/`** or container **`/app/data`** for stack-local state; do not commit secrets or large blobs here. |
| **`docker/`** | Compose files, Dockerfiles, image build context. |
| **`docs/`** | Runbooks (`docs/runbooks/`) and wiki (`docs/wiki/`). |
| **`plugins/`** | Tool/plugin manifest JSON consumed by the platform. |
| **`requirements/`** | Supplementary requirement sets / pins where used. |
| **`scripts/`** | Developer and ops shell helpers. |
| **`tests/`** | Cross-cutting unit, integration, e2e, and load tests. |

**Convention:** keep **`services/api/static/`** and **`services/api/templates/`** as the only home for the HTTP UI assets—avoid duplicating `static/` or `templates/` at repo root so there is one canonical place to edit the UI.

## Agent System (MAKER Framework)

Spectra uses the **MAKER** framework: Maximal Agentic decomposition, K-threshold Error mitigation, and Red-flagging.

### Agent Roles (12 Agents)

| Agent | Role | Temperature | Description |
|-------|------|-------------|-------------|
| ScopeAgent | Scope | 0.1 | Parses targets (IPs, domains, CIDRs) from user input |
| ToolSelectorAgent | Tool Selection | 0.3 | Selects and configures the right security tool for each task |
| MissionController | Planning | 0.4 | Creates PTES-aligned mission plans, handles steering |
| ExploitCrafter | Exploitation | 0.7 | Selects exploits, configures payloads, iterative retry |
| ExploitVerifier | Verification | 0.2 | Verifies exploit results and chains |
| POCDeveloper | Code Gen | 0.2 | Writes custom exploit scripts (Python/Go/Bash) |
| VectorGenerator | Analysis | 0.3 | Generates attack vectors from discovered services |
| SafetySupervisor | Safety | 0.1 | Blocks dangerous commands via regex + LLM analysis |
| PostExploitation | Post-Exploit | 0.3 | Plans privilege escalation, persistence, lateral movement |
| ReporterAgent | Reporting | 0.3 | Generates PTES-standard assessment reports |
| ReconIntelAgent | RECON_INTEL | 0.3 | Gathers OSINT and reconnaissance intelligence on targets |
| DebriefAgent | Learning | 0.3 | Post-mission analysis: extracts lessons for memory |

### Consensus System (K-Threshold Voting)

Critical decisions pass through quality gates where multiple LLM instances vote:

| Gate | When | Voters | Threshold | Min Confidence |
|------|------|--------|-----------|----------------|
| PLAN | Mission planning | 3 | 2/3 | 70% |
| TOOL_SELECTION | Each tool pick | 2 | 2/2 | 50% |
| PAYLOAD | Exploit crafting | 3 | 2/3 | 70% |
| REPLAN | Plan changes | 3 | 2/3 | 60% |
| EXECUTION | High-risk actions | 3 | 3/3 | 80% |
| OUTPUT_PARSING | Parsed facts from tool output | Micro-agent voting | Majority | — |
| TOOL_PICK | Next tool in decomposed tasks | Micro-agent voting | Majority | — |
| RED_FLAG | Corrupt or malformed output | Discard output | — | — |

### Pentest frameworks (YAML)

Framework specs live under `spectra_platform/services/mission/frameworks/*.yaml` (`ptes`, `owasp`, `nist`). Phase order, milestones, technique categories, and UI timelines are loaded at runtime—no hardcoded `AssessmentPhase` lists in application code.

---

## Context Management

The `ContextManager` (`spectra_platform/services/ai/context.py`) prevents prompt explosion by budgeting tokens across context sections with priority-based allocation.

### Priority Levels

| Priority | Level | Examples |
|----------|-------|---------|
| CRITICAL (0) | Always included | System prompt, task instruction |
| HIGH (1) | Truncated to fit | Current target/findings, tool output |
| MEDIUM (2) | Included if budget allows | Memory lessons, playbook recommendations |
| LOW (3) | Dropped first | RAG context, methodology reference |
| OPTIONAL (4) | Best-effort | Historical stats |

- Default budget: **6000 tokens** per prompt
- Sections sorted by priority; lower-priority sections are truncated or dropped when budget is exceeded
- Tool output auto-truncated: **3000 chars stdout**, **500 chars stderr** for LLM context

---

## Credential Store

The `CredentialStore` (`spectra_platform/services/mission/credentials.py`) captures discovered credentials during missions for reuse by subsequent tools.

- **Per-mission, in-memory** — credentials scoped to the mission lifecycle
- **Auto-extraction** — regex patterns extract credentials from tool output (Hydra, generic login patterns)
- **Deduplication** — same user/pass/host/service combo stored once
- **Capacity limit** — max 100 credentials per mission
- **Prompt injection** — `get_summary_for_prompt(host)` builds compact credential context for LLM
- **Attack surface export** — `to_dicts()` for inclusion in mission findings

---

## RAG (Retrieval-Augmented Generation)

PostgreSQL **pgvector** semantic search lives in the **`spectra_ai`** package (`services/ai/src/spectra_ai/rag.py`). The platform uses **`spectra_platform.services.ai.knowledge`** as the facade (`get_rag_service`, `get_mission_context`, etc.) and **`spectra_platform.services.rag.service`** (`RAGFacade`) for higher-level indexing.

### Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `RAGService` | `services/ai/src/spectra_ai/rag.py` | Document storage, cosine similarity search |
| `EmbeddingService` | `services/ai/src/spectra_ai/embeddings.py` | Embeddings via API provider or local fastembed |

### How It Works

1. **Embedding** — Text is embedded via the configured embedding provider (local fastembed or any OpenAI-compatible API). Configure `EMBEDDING_MODEL` to select the model.
2. **Storage** — Embeddings stored in a `rag_documents` PostgreSQL table as a **`vector(dim)`** column (HNSW index), with JSON **`metadata`** for extra fields (e.g. **`user_id`** for tenant-scoped mission retrieval).
3. **Search** — Query embedded; SQL pre-filters **`doc_type`**, optional **`metadata->>'user_id'`**, and optional session exclusion before ordering by distance.

### Document Types

| Type | Source | Indexed When |
|------|--------|--------------|
| `finding` | Mission findings | Mission completes (via `RAGFacade`) |
| `exploit_success` | Successful attack vectors | Mission checkpoint |
| `mission_summary` | Mission rollup text | Mission checkpoint |
| `lesson` | Debrief / `[LEARN]` log lines | Mission checkpoint |
| `tool_output` | Tool stdout summaries | Mission checkpoint |
| `cve` | CVE intelligence data | CVE DB scripts |
| `tool_doc` | Tool documentation | Tool docs indexed |
| `knowledge` | Knowledge base articles | Manual ingestion |

### Configuration

```python
RAGConfig(
    embedding_model="text-embedding-3-small",  # OpenAI-compatible model key
    embedding_dim=1536,                         # Auto-adapts to actual dimension
    default_top_k=5,                            # Results per query
    min_score=0.5,                              # Cosine similarity threshold
    batch_size=500,                             # Indexing batch size
)
```

Mission planning passes **`user_id`** and excludes the **current** `mission_id` session when pulling “past approaches” so prompts do not prefer in-flight rows. The shared **`RAGRequest`** model in `spectra_domain` carries the same optional search fields (`doc_types`, `user_id`, `exclude_session_id`, …) for both the **AI microservice** HTTP API and **in-process** `get_rag_service()` callers.

---

## Execution Pipeline

```text
User enters target + directive
        │
        ▼
  MissionController creates plan
        │ (validated at PLAN gate)
        ▼
  For each task in plan:
        │
        ├─ tool_selector → picks tool → ToolExecutionService
        │  (ContextManager assembles prompt with memory + RAG + credentials)
        │                                      │
        │                        ┌──────────────┘
        │                        ▼
        │              SafetySupervisor checks command
        │                        │
        │                  ┌─────┴─────┐
        │                SAFE        BLOCKED
        │                  │
        │                  ▼
        │         Sandbox worker executes tool via per-mission queue
        │                  │
        │                  ▼
        │         Output parsed → Findings → Attack Surface updated
        │         Credentials extracted → CredentialStore
        │                  │
        │                  ▼
        │         Memory records tool result + OS detection
        │
        ├─ exploit_crafter → iterative exploitation loop
        │         CVE intel → Memory → RAG → Credential Store → Exploit selection
        │         Retry with different payloads/strategies
        │         On success: record chain to memory + playbook
        │
        ├─ reporter → generates PTES report
        │
        ▼
  Mission complete → post-mission learning
        │
        ├─ DebriefAgent extracts lessons → MissionMemory
        ├─ PlaybookEngine exploit patterns → persisted to disk
        ├─ RAG indexes mission findings
        ├─ False positive detection (repeated info findings)
        └─ OS profile update
```

---

## Learning System (3 Layers)

### Layer 1: Persistent Memory (`memory.py`)

**Learning data** is stored as JSON files in `data/cache/`:

- **tool_lessons.json** — which tools produced findings for which services
- **exploit_lessons.json** — successful exploit chains with CVEs
- **target_profiles.json** — effective/ineffective tools per OS family
- **false_positives.json** — noisy template IDs to skip

Debrief lessons are auto-saved after every mission by the `DebriefAgent`.

**Exploit intelligence** (Metasploit modules, CISA KEV catalog, Exploit-DB entries, CVE knowledge base) is cached in PostgreSQL via the `CacheEntry` model (`spectra_platform/services/ai/exploit_db.py`). At startup, the database is auto-initialized in the background if cached data is present. First-time setup requires an admin download via **Settings → Data Sources**, or the scheduler's `exploit_db_refresh` task handles it automatically.

### Layer 2: Playbook Engine (`playbook.py`)

Deterministic service-to-tool mapping (no LLM needed):

- HTTP → nmap → nuclei → nikto → gobuster → sqlmap
- SSH → nmap with scripts → hydra (default creds only) → searchsploit
- SMB → nmap with smb-vuln scripts → metasploit ms17-010
- FTP → nmap with ftp-anon → hydra
- WordPress → wpscan → nuclei wordpress templates

Exploit patterns learned during missions are persisted to disk and loaded on restart.

### Layer 3: RAG Indexing

Mission outcomes (findings, tools used, successful strategies) are indexed into the RAG store. Future missions query this for relevant prior knowledge.

### CVE Intelligence (`cve_intel.py`)

Built-in database of 25+ commonly exploited CVEs. Correlates discovered service versions to known exploits:

```text
nmap finds Apache 2.4.49
    → cve_intel returns CVE-2021-41773 (path traversal, CRITICAL, VERSION MATCH)
    → exploit_crafter uses this as primary candidate
```

### Grounding Framework (`grounding.py`)

Anti-hallucination mechanisms:

- Tool output validation (signature pattern matching)
- Evidence extraction (meaningful lines only, not full output)
- Confidence tracking with decay
- Agents must cite concrete evidence in reasoning

---

## Service Architecture

Spectra runs as four independently deployable microservices. Each image sets
`SERVICE_MODE` so shared configuration (for example database pool sizing in
`spectra_platform.core.config`) can adapt. **Only the Core API** (`spectra_api`) uses that
value for FastAPI router mounting (`api` / `all` / `""` = full surface; see
`microservices-split.md`). AI, scheduler, and worker are **separate ASGI apps**
with their own entrypoints.

### Services and Roles

| Service | Typical `SERVICE_MODE` on image | Port | Role |
|---------|---------------------------------|------|------|
| **App (Core API)** | `api` (or `all` in dev runners) | 5000 | Web UI, REST API, mission orchestration, user management |
| **AI Service** | `ai` | 5010 | LLM routing, embeddings, RAG queries via TensorZero |
| **Scheduler** | `scheduler` | 5011 | Background tasks — sandbox watchdog, backups, metrics |
| **Worker** | `worker` | 5012 | Tool execution from PostgreSQL job queue in sandboxes |

For development or single-node **API** processes, `SERVICE_MODE=all` loads the same full `spectra_api` router set as `api`.

### Directory Layout

```text
spectra/
├── packages/platform/src/spectra_platform/
│   ├── _meta/              # App metadata (version, build info)
│   ├── auth/               # Security — JWT, RBAC, encryption, rate limiting
│   ├── core/               # Config, database, security, cache, events, redis
│   ├── di/                 # Dependency injection — container, protocols, service auth
│   ├── infrastructure/     # Queue, events, background tasks, metrics
│   ├── mission/            # Mission FSM, enums, helpers
│   ├── models/             # SQLAlchemy ORM models
│   ├── repositories/       # Repository pattern data access
│   ├── services/           # Domain services (ai, mission, tools, billing, …)
│   ├── telemetry/          # Observability
│   └── utils/              # Shared utilities
├── services/api/           # spectra_api: HTTP app, static UI, Jinja templates
├── services/{ai,scheduler,worker}/
├── packages/{common,domain,tools-core}/src/
├── plugins/                # Tool plugin JSON configs
├── config/                 # Build configs (tailwind, postcss)
├── docker/                 # Docker Compose files, Dockerfiles, Caddyfile
├── scripts/                # Ops scripts, test runners
├── tests/                  # Unit, integration, e2e, load tests
└── docs/wiki/              # This documentation
```

### Communication Patterns

```text
┌──────────┐    HTTP + Service Auth     ┌────────────┐
│  Core API │ ─────────────────────────→ │ AI Service │
│  (app)    │                            └────────────┘
│           │    PG Job Queue (INSERT)
│           │ ─────────────────────────→ ┌────────────┐
│           │    PG LISTEN/NOTIFY        │   Worker   │
│           │ ←────────────────────────  │            │
└──────────┘                             └────────────┘
      ↕  PG LISTEN/NOTIFY
┌──────────┐
│ Scheduler │
└──────────┘
```

| Pattern | Mechanism | Used For |
|---------|-----------|----------|
| **HTTP + Service Auth** | `X-Service-Auth` header, `ServiceAuthMiddleware` | API → AI Service requests |
| **PG Job Queue** | `SELECT ... FOR UPDATE SKIP LOCKED` on `job_queue` table | API → Worker task dispatch |
| **PG LISTEN/NOTIFY** | `pg_notify()` on channels like `spectra_jobs_mission_{id}` | Real-time event delivery across all services |
| **Redis** | Shared distributed rate-limiting backend | Rate-limit counters shared across app replicas |

### Shared vs Service-Specific Code

| Layer | Path | Rule |
|-------|------|------|
| **Shared** | `spectra_platform/core/`, `spectra_platform/models/`, `spectra_platform/repositories/` | Used by all services. Must NOT import service-specific code. |
| **Service: API** | `services/api/src/spectra_api/` (`spectra_api.main:app`) | Routers, schemas, bootstrap, UI templates, API-owned settings/setup services |
| **Service: AI** | `services/ai/src/spectra_ai/main.py`, `spectra_platform/services/ai/` | LLM clients, agents, RAG |
| **Service: Worker** | `services/worker/src/spectra_worker/` (`spectra_worker.main:app`) | Job queue consumer, tool execution |
| **Service: Scheduler** | `services/scheduler/src/spectra_scheduler/main.py` | Background task loops |

Import boundaries are enforced by `scripts/check_import_boundaries.py` — shared packages cannot have top-level imports of service-specific modules.

See [Microservices Architecture](microservices-split.md) for the full service split documentation.

---

## Caching Architecture

Spectra uses a dual-layer caching system: PostgreSQL for persistent application cache and Redis for distributed rate limiting.

### PostgreSQL CacheService

`CacheService` (`spectra_platform/core/cache.py`) provides the primary application cache backed by the `cache_entries` table:

- **Persistent** — survives restarts, shared across all service instances
- **TTL support** — entries expire via `expires_at` column
- **Namespaced keys** — prefixes like `cache:tool:`, `cache:finding:`, `cache:rag:`, `cache:stats:`
- **Decorator API** — `@cache.cached(ttl=300, prefix="tool")` for easy memoization
- **Stats tracking** — hit/miss/set/delete counters for observability

### Redis Cache

`RedisCache` (`spectra_platform/core/redis_client.py`) provides fast, ephemeral caching and distributed rate limiting:

- **Connection pooling** — singleton `RedisConnectionPool` with graceful degradation when Redis is unavailable
- **JSON serialization** — values stored as JSON strings
- **TTL support** — `setex` for time-bounded entries
- **Pattern deletion** — `delete_pattern()` for bulk cache invalidation
- **Rate limiting** — shared counters across app replicas via `RATE_LIMIT_STORAGE=redis://`

When Redis is unavailable, the system degrades gracefully: `RedisCache` methods return `None`/`False`/`0` instead of raising errors. For local development or testing, `RATE_LIMIT_STORAGE=memory://` works without Redis.

### Cache Decision Guide

| Use Case | Backend | Why |
|----------|---------|-----|
| Tool output, findings, RAG results | PostgreSQL `CacheService` | Persistent, survives restarts, shared across instances |
| Rate-limit counters | Redis `RedisCache` | Fast, atomic, shared across replicas |
| Session/temporary data | Redis `RedisCache` | Ephemeral, fast TTL expiry |

---

## Service Architecture (Gateway Pattern)

Spectra uses a **ServiceRegistry** pattern (`spectra_platform/services/gateway/service_registry.py`) to transparently route between in-process and remote implementations. When a gateway URL is configured, the registry instantiates an HTTP client adapter; otherwise it creates the local implementation.

### Extractable Services

| Service | Config Setting | Local Implementation | Protocol |
|---------|---------------|---------------------|----------|
| Sandbox Orchestrator | `SANDBOX_ORCHESTRATOR_URL` | `SandboxPool` (`spectra_platform/services/tools/sandbox/`) | HTTP `/containers/*` |

### What Stays In-Process

| Component | Reason |
|-----------|--------|
| PostgreSQL | Single `DATABASE_URL` is sufficient; use managed DB for HA |
| Embeddings | Handled by local fastembed or API provider — no separate service |
| RAG / Vector Search | Runs on the same PostgreSQL DB (pgvector) |
| Agent orchestration | Core logic, not a hot path for scaling |

### ServiceRegistry Pattern

```python
from spectra_platform.services.gateway import get_service_registry

registry = get_service_registry()
pool = await registry.get_sandbox_orchestrator()  # Remote or local Docker
```

The registry uses lazy initialization with async locks (double-checked locking). Services are created on first access and cached. Call `registry.invalidate("sandbox")` to force re-creation after config changes.

### Server Pool Management

For scaling across multiple servers, see the [Scaling Guide](scaling.md). Spectra includes a `ServerPoolManager` that tracks server nodes with weighted least-connections load balancing. Service types include `sandbox_worker`, `db`, and `storage`.

---

## LLM Routing (`router.py`)

TensorZero-powered smart routing. See [Configuration](configuration.md) for all LLM settings.

### Task Tiers

| Tier | Tasks | Recommended Model |
|------|-------|-------------------|
| 1 (Simple) | Scope, tool selection, safety | qwen2.5:3b, gpt-4o-mini |
| 2 (Moderate) | Planning, consensus, reporting | gpt-4o-mini, claude-3-haiku |
| 3 (Complex) | Exploit crafting, POC generation | gpt-4o, claude-3.5-sonnet |

### Fallback Chain

```text
Primary provider → Fallback provider(s) → Mock (testing)
```

---

## Safety Mechanisms

1. **SafetySupervisor** — regex blocklist + LLM analysis of every command
2. **Anti-brute-force** — blocks rockyou.txt, large wordlists, file-based credential lists
3. **Plugin signing** — Ed25519 signatures required in production (see [Plugins](plugins.md))
4. **Consensus voting** — multi-model validation for high-risk actions
5. **Container isolation** — all tools run in per-mission [sandboxes](sandboxes.md)
6. **Scope enforcement** — agents only target authorized hosts

For full security details, see the [Security Guide](security.md).
