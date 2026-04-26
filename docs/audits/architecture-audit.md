# Spectra Project Architecture Audit Report

**Date**: 2026-04-27
**Auditor**: Automated Codebase Analysis
**Version Audited**: `2026.03.07` (from `app/_meta/version.py`)

---

## 1. Top-Level Structure

### Current Layout
```
Spectra/
├── app/                  # Main application package (monolith + microservices)
├── plugins/              # 26 JSON plugin definitions (data, not Python)
├── tests/                # Full test suite (unit, integration, e2e, load, soak, performance)
├── docs/                 # Wiki-style documentation
├── docker/               # Dockerfiles, compose files, Caddy configs, target envs
├── scripts/              # Developer tooling, ops scripts, CI helpers
├── alembic/              # Database migration tooling
├── config/               # Config files (alembic.ini, tensorzero.toml, tailwind.config.js)
├── requirements/         # Per-service requirements files (base, app, ai, scheduler, worker, dev)
├── .github/              # CI (ci.yml), Release (release.yml), UI tests (ui-e2e.yml)
├── keys/                 # Plugin signing public key only (no private keys in repo)
├── data/                 # Runtime data directory (gitignored)
├── Makefile              # Developer convenience targets
├── pyproject.toml        # Project metadata, ruff config, pytest config, coverage config
├── README.md             # Project overview
├── CONTRIBUTING.md        # Detailed contribution guide
├── .env.example          # Environment template
├── .env.test.example     # Test environment template
└── .env.test            # Local test env (gitignored)
```

### Assessment: ✅ STRONG — Minor Issues

**Positive Findings:**
- All required directories (`app/`, `tests/`, `docs/`, `docker/`, `scripts/`, `plugins/`) are present and well-populated
- `config/` and `requirements/` are properly separated
- Root-level files (Makefile, pyproject.toml, README, CONTRIBUTING) are minimal and focused

**Issues:**
1. ~~**`app/static/` and `app/templates/`** are nested inside the Python application package.~~ ✅ **RESOLVED** — Moved to top-level directories (`static/`, `templates/`).
2. ~~**Service entry points at wrong level**: `app/ai_service.py`, `app/scheduler_service.py`, `app/worker_service.py` are root-level files in `app/` rather than within their respective service modules~~ ✅ **RESOLVED** — Moved to `app/services/ai/__main__.py`, `app/services/scheduler/__main__.py`, and `app/worker/__main__.py`.
3. ~~**`app/version.py`** is at the `app/` root; it belongs in `app/_meta/` or `app/core/`~~ ✅ **RESOLVED** — Moved to `app/_meta/version.py`.
4. **`app/__init__.py`** imports `app.core` for pytest resolution — this is a known workaround but indicates a pytest path issue

---

## 2. Submodule Boundaries

### Current Architecture

The project enforces a **strict layered + service split**:

| Layer | Path | Rule |
|-------|------|------|
| **Shared** | `app/core/`, `app/models/`, `app/repositories/` | Used by all services. Must NOT import service-specific code. |
| **API Service** | `app/api/`, `app/main.py` | Web UI, REST API |
| **AI Service** | `app/services/ai/__main__.py`, `app/services/ai/` | LLM clients, agents, RAG |
| **Worker Service** | `app/worker/__main__.py`, `app/worker/` | Job queue consumer, tool execution |
| **Scheduler Service** | `app/services/scheduler/__main__.py` | Background maintenance tasks |

### Enforcement Mechanism: `scripts/check_import_boundaries.py`

```python
SHARED_PACKAGES = ["app/core", "app/models"]
SERVICE_BOUNDARIES = {
    "app/services/scheduler/__main__.py": ["app.api", "app.worker"],
    "app/worker/__main__.py": ["app.api", "app.services.scheduler.__main__", "app.services.ai.__main__"],
    "app/services/ai/__main__.py": ["app.api", "app.worker", "app.services.scheduler.__main__"],
    "app/worker": ["app.api", "app.services.scheduler.__main__", "app.services.ai.__main__"],
    "app/api": ["app.services.ai"],  # top-level only; lazy imports allowed
}
```

The script uses AST analysis to detect top-level imports of forbidden modules. It is run as part of `make check` and blocks CI if violations are found.

### Circular Dependency Risk: ✅ LOW

- Shared packages (`app/core/`, `app/models/`, `app/repositories/`) have no service-specific imports
- `app/__init__.py` does `import app.core` which is a deliberate workaround for pytest path resolution (documented)
- `app/core/__init__.py` uses lazy-loading via `__getattr__` to avoid circular import issues
- Known cross-service lazy imports (e.g., `app/worker` → `app.services.ai` for RAG) are flagged as warnings, not errors

### `__init__.py` Usage: ✅ WELL-STRUCTURED

- All 51 `__init__.py` files exist and define public APIs
- `app/core/__init__.py` uses a lazy-loading pattern to avoid circular imports
- `app/services/__init__.py` documents that consumers should import from specific submodules
- `app/worker/__init__.py` exports a `_WORKER_FUNCTIONS` registry list for the job queue consumer

### Issues:
- The `app/api` → `app.services.ai` boundary allows lazy imports but only at the top level. The enforcement only catches `col_offset == 0` imports, so indented lazy imports inside functions are allowed and not checked.
- There is no enforced boundary between `app/services/mission/` and `app/services/tools/`, though they clearly depend on each other at runtime.

---

## 3. Dynamic Codebase

### Plugin System Architecture

Spectra uses a **data-driven plugin system** where tools are defined as JSON files rather than Python classes:

```
plugins/
├── nmap.json         # Network scanner
├── nuclei.json       # Vulnerability scanner
├── sqlmap.json       # SQL injection tool
├── ... (26 total)
└── (each file ~129 lines)
```

**Plugin Schema** (from `plugins/nmap.json`):
```json
{
  "id": "nmap",
  "name": "Nmap",
  "version": "1.0.0",
  "category": "discovery",
  "metadata": { "capabilities": [...], "risk_level": "low", ... },
  "installation": { "method": "apt", "commands": [...], "verification_regex": "..." },
  "execution": { "command": "nmap", "args_template": "...", "timeout": 600 },
  "parsing": { "format": "xml", "mapping": {...} },
  "stealth": { "rate_limit": null, "delay_ms": 1000, "extra_args": {...} },
  "signature": "2b7822cad8f5195dd185b0cf72fa31fc3a7966a0...",
  "resources": { "tier": "light" }
}
```

### Dynamic Loading Mechanism: `ToolRegistry`

**File**: `app/services/tools/registry/__init__.py`

The `ToolRegistry` class manages the full plugin lifecycle:
1. **`load_plugins()`** — scans `plugins_dir` for `*.json`, validates via `PluginValidator`, returns `dict[str, RegisteredTool]`
2. **`validate_plugin()`** — schema validation (Pydantic models) + Ed25519 signature verification when `safe_mode=True`
3. **`install_tool()`** — delegates to `PluginInstaller` to execute install commands
4. **`add_plugin()`** — accepts uploaded plugin data, validates, saves to disk atomically
5. **`get_tool_for_ai()`** — returns AI-formatted tool info (command, args_template, capabilities, risk_level)

**Registry Singleton Pattern**:
```python
_registry_instance: ToolRegistry | None = None

def get_registry() -> ToolRegistry:
    if _registry_instance is None:
        _registry_instance = ToolRegistry()
    return _registry_instance

async def initialize_registry(...):
    _registry_instance = ToolRegistry(...)
    await _registry_instance.load_plugins()
    return _registry_instance
```

The registry is initialized at startup in `app/core/lifespan.py:_initialize_services()` via `initialize_registry(plugins_dir="plugins", public_key_path="keys/plugin_signing.pub", safe_mode=settings.PLUGIN_SAFE_MODE)`.

### Mission/Plan Factory Patterns

**Mission Management** (`app/services/mission/manager/`):
- `MissionManager` is the main orchestrator with state machine
- Mission lifecycle via `executor/` submodule with `MissionExecutor`
- Adaptive replanning via `exploitation.py` with `ExploitationSession`

**No generic factory/registry pattern** for missions — they are created through `MissionManager.create()` and tracked via the database with `MissionStatus` enum.

### Agent System

12 specialized agents defined in `app/services/ai/agents/`:
- `ScopeAgent`, `ToolSelectorAgent`, `MissionController`, `ExploitCrafter`, `ExploitVerifier`, `POCDeveloper`, `VectorGenerator`, `SafetySupervisor`, `PostExploitation`, `ReporterAgent`, `ReconIntelAgent`, `DebriefAgent`

K-threshold consensus voting defined in `app/services/ai/consensus.py`.

### Issues:
- **Plugin system is data-only**: Plugins are JSON files with no code extension point. Adding new tool functionality requires editing Python code in `app/services/tools/`.
- **No mission factory registry**: Missions are created via `MissionManager`, not a generic factory. This is fine but less extensible than the plugin system.
- **No dynamic agent registration**: Agents are hardcoded in the consensus system.

---

## 4. Package Architecture

### Current: Monorepo with 4 Microservices

Spectra runs as 4 independently deployable services controlled by `SERVICE_MODE`:

| Service | Entry Point | Port | Key Dependencies |
|---------|-------------|------|------------------|
| **API** | `app/main.py` + `app/__init__.py` | 5000 | FastAPI, SQLAlchemy, all services |
| **AI** | `app/services/ai/__main__.py` | 5010 | TensorZero, embeddings, RAG |
| **Scheduler** | `app/services/scheduler/__main__.py` | 5011 | PostgreSQL advisory locks, all services |
| **Worker** | `app/worker/__main__.py` | 5012 | Docker SDK, job queue |

### Could This Be Split into Multiple Installable Packages?

**Theoretically YES**, but practically NOT YET. Key observations:

**Extractable as separate packages:**
- `spectra-core` → `app/core/`, `app/models/`, `app/repositories/`, `app/api/schemas/`
- `spectra-ai` → `app/services/ai/`
- `spectra-worker` → `app/worker/`

**Coupling points preventing clean split today:**
1. `app/services/ai/__main__.py` imports `app.services.ai.embeddings`, `app.services.ai.router`, `app.services.ai.rag` — all internal to AI service
2. `app/services/scheduler/__main__.py` imports from `app/services/billing/`, `app/services/infrastructure/backup.py`, `app/services/scaling/`, `app/core/background_tasks.py` — crosses multiple service boundaries
3. `app/worker/__main__.py` imports `app.worker.lifecycle`, `app.core.queue`, `app.services/shell/session_manager.py` — crosses into multiple services
4. `app/core/` is truly shared but has some AI-specific code paths (telemetry, events)
5. Database models (`app/models/`) are shared but have relationships that couple them (Mission → Finding → Exploit → Target)

### Service Communication Patterns

| Pattern | Mechanism | Used For |
|---------|-----------|----------|
| **HTTP + Service Auth** | `X-Service-Auth` header, `ServiceAuthMiddleware` | API → AI Service |
| **PG Job Queue** | `SELECT ... FOR UPDATE SKIP LOCKED` on `job_queue` table | API → Worker task dispatch |
| **PG LISTEN/NOTIFY** | `pg_notify()` on channels | Real-time event delivery |

### Dependency Injection

`app/core/container.py` provides factory functions:
- `get_db_session()` — scoped database session
- `get_job_queue()` — singleton `PostgresJobQueue`
- `get_tool_registry()` — singleton `ToolRegistry`
- `get_sandbox_pool()` — singleton `SandboxPool`
- `get_storage_service()` — new instance per call

### Issues:
- The DI container is minimal and uses module-level singletons rather than a full IoC container
- Circular import risk is managed through lazy loading rather than proper interface segregation

---

## 5. Configuration & Environment

### Configuration System: Pydantic Settings

**File**: `app/core/config.py` — `Settings` class inheriting from `pydantic_settings.BaseSettings`

**Bootstrap Flow**:
```
.env file → Settings model → get_settings() → validated settings
                           → auto-generate JWT_SECRET_KEY, SECRET_KEY, SERVICE_AUTH_SECRET, ENCRYPTION_KEY if empty
                           → validate_payment_provider (reject noop in production)
                           → validate_rate_limit_storage (Redis connectivity check)
```

**Startup Sequence** (from `app/core/lifespan.py`):
1. `_validate_noop_payment()` — prevent free-access in production
2. `_validate_stripe_webhook_secret()` — require webhook secret when using Stripe
3. `_validate_rate_limit_storage()` — verify Redis connectivity
4. `_initialize_database()` → cache init → DB connectivity → secret bootstrap → runtime settings hydration → storage init → rate limit validation → startup checks
5. `_seed_default_data()` — seed plans, init service registry
6. `_initialize_services()` → preload embeddings (in-process or deferred to ai-svc) → init exploit DB → init tool registry → init sandbox pool → init server pool → run startup tasks
7. `_start_event_bridge()` — WebSocket bridge for real-time events
8. `_config_change_listener()` — PG LISTEN for multi-replica config sync
9. `_blacklist_change_listener()` — PG LISTEN for token invalidation

### Environment Files

| File | Purpose | Git Status |
|------|---------|------------|
| `.env.example` | Template with all variables | Tracked |
| `.env.test.example` | Test env template | Tracked |
| `.env.test` | Local test overrides (API keys for live LLM tests) | `.gitignore`d |
| `.env` | Local development overrides | `.gitignore`d |

### Issues:
- No `SERVICE_MODE` validation in config — invalid values fall back to loading all routers (documented as intended behavior, but no hard validation)
- ENCRYPTION_KEY auto-generation to filesystem (`/app/data/.encryption_key`) works in containers but is fragile for local development
- No `PYTHONPATH` defaults in Docker — relies on `PYTHONPATH=/app` in Dockerfiles

---

## 6. Documentation

### Documentation Structure

```
docs/
├── wiki/
│   ├── home.md
│   ├── architecture.md      ← main architecture doc
│   ├── configuration.md
│   ├── deployment-guide.md
│   ├── deployment.md
│   ├── development.md
│   ├── operations.md
│   ├── scaling.md
│   ├── plugins.md
│   ├── microservices-split.md  ← service split documentation
│   ├── worker-system.md
│   ├── testing-strategy.md
│   ├── _Sidebar.md
│   └── ... (19 total wiki files)
└── audits/
    ├── architecture/
    ├── operations/
    └── ui/
```

### README.md Assessment

- ✅ Good overview with key features
- ✅ Links to all wiki documents
- ✅ Quick start section (3 steps)
- ✅ API overview table
- ✅ Development setup with test commands
- ✅ References microservices-split.md and ops/README.md
- ⚠️ Mentions "12 specialized agents" but the actual agent count may have changed
- ⚠️ No changelog in repo (referenced as `changelog.html` in templates)

### CONTRIBUTING.md Assessment

- ✅ Comprehensive development setup
- ✅ Architecture overview with diagrams
- ✅ Code style guide (ruff, Python 3.11+)
- ✅ Testing guide with test matrix
- ✅ PR review checklist
- ✅ Database migration guide
- ✅ Ops script index reference
- ⚠️ Mentions `requirements/*.txt` but the project now uses `requirements/` directory with individual txt files

### Documentation Accuracy Issues

- `docs/wiki/microservices-split.md` — referenced in README and architecture.md but may not reflect current state of `SERVICE_MODE` implementation
- `docs/wiki/deployment.md` vs `docs/wiki/deployment-guide.md` — two deployment docs may cause confusion
- `docs/wiki/architecture.md` section "Service Architecture (Gateway Pattern)" mentions `ServiceRegistry` pattern with `SANDBOX_ORCHESTRATOR_URL` but this appears to be aspirational/incomplete

### Issues:
- No architecture diagram files (e.g., C4 model, sequence diagrams) in the repo
- Wiki is in markdown but not built/published anywhere — it's local-only documentation
- `scripts/ops/README.md` exists — ops scripts have their own documentation

---

## 7. Docker & DevOps

### Dockerfiles (8 total, all multi-stage)

| Dockerfile | Base Image Pattern | Multi-stage | Purpose |
|------------|-------------------|-------------|---------|
| `Dockerfile.api` | `python:3.11-slim` | ✅ (builder + runner) | Main API service |
| `Dockerfile.ai` | `python:3.11-slim` | ✅ | AI service (embeddings, LLM) |
| `Dockerfile.worker` | `python:3.11-slim` | ✅ | Worker service |
| `Dockerfile.scheduler` | `python:3.11-slim` | ✅ | Scheduler service |
| `Dockerfile.caddy` | `caddy:2-alpine` | ❌ | Reverse proxy |
| `Dockerfile.test` | `python:3.11-slim` | ✅ | Test runner |
| `Dockerfile.playwright` | `node:20-alpine` | ✅ | UI test runner |
| `targets/Dockerfile.vuln-*` | Various | Mixed | Target environments for testing |

**Dockerfile Optimisations:**
- All Python services use `python:3.11-slim` as base
- Multi-stage builds separate build dependencies from runtime
- Resource limits defined in docker-compose.yml (cpu, memory)
- Security defaults applied: `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`
- `read_only: true` + `tmpfs` for API containers
- Health checks on all services

### Docker Compose Files (4 total)

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Local development stack |
| `docker-compose.test.yml` | Full test stack |
| `docker-compose.swarm.yml` | Production Swarm deployment |
| `targets/docker-compose.targets.yml` | Vulnerable target environments |

**docker-compose.yml Services (9 total)**:
- `garage` — S3-compatible storage (512M RAM limit)
- `db` — PostgreSQL with pgvector (512M RAM limit)
- `redis` — Redis (512M RAM limit)
- `caddy` — Reverse proxy
- `app` — Main API service
- `ai-svc` — AI service
- `clickhouse` — Analytics DB for TensorZero
- `tensorzero` — LLM gateway
- `scheduler` — Background task scheduler
- `worker` — Tool execution worker

**Network Architecture**:
- `frontend` bridge — external facing
- `backend` bridge — internal, `internal: true`

### Issues:
- No separate `Dockerfile.main` or entry point for the monolithic `app/` — all services share the same app code with different `SERVICE_MODE`
- Garage (`dxflrs/garage:v2.2.0`) is a specific external image — no build Dockerfile for it
- `docker/docker-compose.test.yml` runs a `settings-test-runner` service not defined in the main compose — it's a separate test harness
- No image scanning in CI pipeline (`Dockerfile.test.dockerignore` exists but no Trivy or similar in the CI workflow)
- No separate `.dockerignore` at project root (only at `docker/Dockerfile.test.dockerignore`)

---

## 8. Scripts & Tooling

### Root Scripts

```
scripts/
├── check_import_boundaries.py   # AST-based import enforcement (important!)
├── deploy.sh                    # Production deployment script
├── rollback.sh                  # Version rollback script
├── health_check.sh              # Pre-deploy health verification
├── first_run.sh                 # First-time setup script
├── sign_plugin.py               # Cryptographic plugin signing
├── live_smoke.py                # Live API smoke tests
├── test.sh                      # Docker-based test runner
├── version.py                   # Version stamp utility
└── ops/                         # Operations subdirectory
    ├── golden_image_refresh.sh
    ├── harden_server.sh
    ├── incident_response.sh
    ├── log_management.sh
    ├── migrate_server.sh
    ├── s3_management.sh
    ├── swarm_deploy.sh
    ├── worker_management.sh
    └── README.md
```

### Scripts Assessment

| Script | Purpose | Quality |
|--------|---------|---------|
| `check_import_boundaries.py` | Enforces architectural boundaries via AST | ✅ Excellent — comprehensive, well-documented |
| `deploy.sh` | Production deployment | Needs review |
| `rollback.sh` | Version rollback | Needs review |
| `health_check.sh` | Pre-deploy verification | Needs review |
| `sign_plugin.py` | Ed25519 plugin signature generation | ✅ Functional |
| `live_smoke.py` | Live API smoke tests | ✅ Functional |
| `test.sh` | Unified test runner | ✅ Comprehensive (unit, integration, coverage) |

**ops/ scripts** (`scripts/ops/README.md` exists with documentation):
- All ops scripts appear to be shell scripts for infrastructure management
- `incident_response.sh` — suggests mature incident handling process
- `swarm_deploy.sh` — production-grade deployment

### Tooling Inventory

- **Linter**: Ruff (configured in `pyproject.toml`)
- **Formatter**: Ruff format (120 line length)
- **Type Checker**: Pyright (configured in `pyproject.toml`)
- **Test Runner**: pytest with asyncio strict mode
- **Coverage**: Coverage.py with `cov-fail-under=67.4`
- **DB Migrations**: Alembic
- **CSS Build**: Tailwind CSS (`tailwind.config.js` in `config/`)
- **Package Manager**: pip (via `requirements/*.txt`)

### Issues:
- No `pre-commit` hook configured (only CI enforcement)
- No automated code quality checks before merge (only `make check` locally)
- `scripts/version.py` and `app/_meta/version.py` serve similar purposes — potential duplication
- `scripts/first_run.sh` — needs review for idempotency

---

## Proposed New Directory Structure

Below is a **target architecture** that addresses all identified issues while maintaining backward compatibility:

```
spectra/                          # Root — no change needed
├── app/                          # APPLICATION PACKAGE
│   ├── __init__.py               # Keep workaround for pytest
│   ├── main.py                   # API entry point (keep here or move to app/api/__main__.py)
│   │                           # NOTE: ai_service, scheduler, worker entry points
│   │                           # moved to app/services/<name>/__main__.py and app/worker/__main__.py
│   ├── _meta/                    # NEW: Metadata (moved from app root)
│   │   ├── __init__.py
│   │   └── version.py            # MOVED: from app/version.py
│   ├── core/                     # KEEP: shared infrastructure
│   ├── models/                   # KEEP: shared ORM models
│   ├── repositories/             # KEEP: shared data access
│   ├── api/                      # KEEP: HTTP layer (API service only)
│   │   ├── routers/
│   │   ├── schemas/
│   │   └── __init__.py
│   ├── worker/                   # KEEP: Job consumer (Worker service only)
│   │   ├── tool_jobs.py
│   │   ├── command_jobs.py
│   │   ├── vpn_jobs.py
│   │   ├── notification_jobs.py
│   │   ├── report_jobs.py
│   │   ├── helpers.py
│   │   ├── lifecycle.py
│   │   ├── __init__.py
│   │   └── __main__.py           # NEW: worker entry point (from worker_service.py)
│   └── services/                 # KEEP: Business logic
│       ├── ai/                   # KEEP: LLM, agents, RAG, embeddings
│       │   ├── agents/
│       │   ├── __main__.py       # NEW: AI service entry point (from ai_service.py)
│       │   └── ...
│       ├── scheduler/            # NEW: Scheduler submodule
│       │   └── __main__.py       # NEW: Scheduler entry point (from scheduler_service.py)
│       ├── mission/
│       ├── tools/
│       └── ... (billing, email, etc.)
├── static/                       # MOVED: from app/static/ (top-level)
│   ├── css/
│   ├── js/
│   └── vendor/
├── templates/                    # MOVED: from app/templates/ (top-level)
│   ├── admin/
│   ├── errors/
│   └── ...
├── plugins/                       # KEEP: JSON plugin definitions
├── tests/                         # KEEP: full test suite
├── docs/                          # KEEP: wiki documentation
├── docker/                        # KEEP: Dockerfiles, compose files
├── scripts/                       # KEEP: developer and ops scripts
├── config/                        # KEEP: alembic, tensorzero, tailwind
├── requirements/                  # KEEP: per-service requirements
├── alembic/                       # KEEP: migrations
├── .github/                       # KEEP: CI workflows
├── keys/                          # KEEP: plugin signing keys
├── data/                          # KEEP: runtime data (gitignored)
├── Makefile                       # KEEP: developer convenience
├── pyproject.toml                 # KEEP: project metadata
├── README.md                      # KEEP: project overview
├── CONTRIBUTING.md                # KEEP: contribution guide
└── .env.example                   # KEEP: environment template
```

### Files to Move (Summary)

| Current Location | Proposed Location | Reason |
|-----------------|-------------------|--------|
| `app/static/` | `static/` | Static assets should not be inside Python package |
| `app/templates/` | `templates/` | Templates should not be inside Python package |
| `app/version.py` | `app/_meta/version.py` | Version belongs with metadata, not at package root |
| `app/ai_service.py` | `app/services/ai/__main__.py` | Service entry points belong in service modules |
| `app/scheduler_service.py` | `app/services/scheduler/__main__.py` | Same as above |
| `app/worker_service.py` | `app/worker/__main__.py` | Same as above |

### Coupling Points Identified

1. **`app/api/` → `app/services/ai/`** — Allowed as lazy imports. The API service reads AI data (cost tracking, CVE intel, memory) but doesn't call LLM inference directly.
2. **`app/worker/` → `app/services/ai/`** — Known coupling for RAG features; flagged as warning in boundary checker.
3. **`app/services/scheduler/__main__.py` → `app/services/*`** — Imports from billing, infrastructure/backup, scaling, core/background_tasks — very high coupling.
4. **`app/services/mission/` → `app/services/tools/`** — Mission executor depends on tool registry and sandbox.
5. **`app/core/` → `app/services/`** — No direct imports (enforced); but core does emit events that services subscribe to.

---

## Summary Table

| Area | Status | Score | Key Issue |
|------|--------|-------|-----------|
| **Top-Level Structure** | 🟢 Strong | 8/10 | `static/` and `templates/` moved to top-level; entry points moved to service modules |
| **Submodule Boundaries** | 🟢 Strong | 9/10 | Well-enforced with AST checker; minor gap with lazy import detection |
| **Dynamic Codebase** | 🟡 Partial | 6/10 | Plugin system is data-driven only; no code-based extension points |
| **Package Architecture** | 🟡 Monorepo | 7/10 | Could split into `spectra-core`, `spectra-ai`, `spectra-worker` but coupling is moderate |
| **Configuration & Bootstrap** | 🟢 Strong | 8/10 | Comprehensive startup validation and secret management |
| **Documentation** | 🟡 Good | 7/10 | Comprehensive but some wiki files may be outdated; no diagrams |
| **Docker & DevOps** | 🟢 Strong | 8/10 | 8 multi-stage Dockerfiles, resource limits, health checks; no image scanning |
| **Scripts & Tooling** | 🟢 Strong | 8/10 | Excellent boundary checker; ops scripts well-documented |

---

## Recommended Priority Actions

1. ~~**High Priority**: Move `app/static/` and `app/templates/` to top-level directories (`static/` and `templates/`)~~ ✅ **DONE**
2. ~~**High Priority**: Move service entry points (`ai_service.py`, `scheduler_service.py`, `worker_service.py`) into their respective service submodules as `__main__.py`~~ ✅ **DONE**
3. ~~**Medium Priority**: Create `app/_meta/` submodule and move `app/version.py` there~~ ✅ **DONE**
4. **Medium Priority**: Add image scanning (Trivy) to CI pipeline
5. **Medium Priority**: Add pre-commit hooks for import boundary checks and ruff linting
6. **Low Priority**: Update wiki documentation to reflect current `SERVICE_MODE` architecture
7. **Low Priority**: Consider adding architecture diagrams (C4 model) to `docs/`
