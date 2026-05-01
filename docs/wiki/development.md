# Development

[← Wiki Home](home.md) | [Architecture](architecture.md) | [Frontend Patterns](frontend-patterns.md) | [Design Tokens](design-tokens.md) | [Operations](operations.md) | [Plugins](plugins.md)

---

Local development setup, testing, code structure, and contributing guidelines.

## Code quality and structure

Ruff and import boundaries are the mechanical gates. For **how we want modules, routers, and async code to read** — including when to split large files — see [Readability and structure](../../docs/contributing/readability-and-structure.md) and the root [CONTRIBUTING.md](../../CONTRIBUTING.md).

---

## Getting Started

### Prerequisites

- Docker Engine 24.0+ and Docker Compose v2.20+
- Python 3.11+ (for local linting/development only — app runs in Docker)
- Git
- Node.js 18+ (for Tailwind CSS builds)

### Local Setup

```bash
git clone <repo-url> && cd spectra
cp .env.example .env
# Edit .env — at minimum set JWT_SECRET_KEY to a secure random value

cd docker
docker compose up -d
```

- **Dev UI:** <http://localhost:5000>
- Create your admin account at `/setup`
- Configure your AI provider through the web UI

Tool binaries land in sandboxes via the golden-image pipeline and on-demand installs from plugin definitions — nothing bulk-installs all plugins at arbitrary container boot by default.

### Pre-commit Hooks

Install pre-commit hooks to catch issues before pushing:

```bash
pip install pre-commit
pre-commit install
```

The hooks (configured in `.pre-commit-config.yaml`) run on every commit:

| Hook | What it does |
|------|-------------|
| `trailing-whitespace` | Removes trailing whitespace |
| `end-of-file-fixer` | Ensures files end with a newline |
| `check-yaml` | Validates YAML syntax |
| `check-added-large-files` | Prevents large files from being committed |
| `ruff` | Lints and auto-fixes Python code |
| `ruff-format` | Formats Python code |
| `check-import-boundaries` | Enforces shared/service import boundaries |

Run all hooks manually:

```bash
pre-commit run --all-files
```

Run a specific hook:

```bash
pre-commit run ruff --all-files
pre-commit run check-import-boundaries --all-files
```

### Local Ops Scripts

For local admin and troubleshooting work, use [Operations](operations.md) as the canonical runbook owner and [scripts/ops/README.md](../../scripts/ops/README.md) for the script-by-script index. The helper scripts default to the standard `spectra-*` container names, which matches the local Docker Compose setup.

### Cursor / Chunkhound MCP

Cursor loads MCP servers from **user-level** `~/.cursor/mcp.json` (the repo’s `.cursor/` directory is gitignored). To run Chunkhound against an index on a remote host (so indexing does not run on your laptop), use SSH stdio in that file. A template with placeholders is committed at [`docs/examples/cursor-chunkhound-mcp.json`](../examples/cursor-chunkhound-mcp.json): copy it to `~/.cursor/mcp.json`, set `USER@YOUR_VPS_HOST`, paths to Python venv and `chunkhound`, and the project directory on the server.

---

## Testing

The primary CI test command is:

```bash
docker compose -f docker/compose.yaml --profile test run --rm settings-test-runner
```

For local iteration, run unit tests through Docker:

```bash
./scripts/test.sh unit
```

For the full verification matrix, release gate criteria, load/performance/soak harnesses, and known gaps, see [Testing Strategy](testing-strategy.md).

### Test Categories

| Category | Command | What it covers |
|----------|---------|---------------|
| **Unit** | `make test-unit` or `./scripts/test.sh unit` | Fast, isolated tests with no external dependencies |
| **Integration** | `make test-integration` or `./scripts/test.sh integration` | Tests requiring live PostgreSQL, Redis, etc. |
| **E2E** | `./tests/run_ui_tests.sh` | Playwright browser tests against running app |
| **Performance** | `make test-performance` or `./tests/run_load_tests.sh performance` | Performance smoke harness |
| **Load** | `make test-load` or `./tests/run_load_tests.sh load` | Burst/load and rate-limit harness |
| **Soak** | `make test-soak` or `./tests/run_load_tests.sh soak` | Mixed-traffic soak/stability harness |
| **Live smoke** | `make test-live-smoke` or `START_STACK=1 ./scripts/test.sh live-smoke` | API/UI/LLM smoke tests against running stack |

### Performance Benchmarks

Run the performance smoke harness to measure route latency, queue drain throughput, and worker concurrency:

```bash
make test-performance
# or
./tests/run_load_tests.sh performance
```

For sustained mixed-traffic stability testing:

```bash
make test-soak
# or
./tests/run_load_tests.sh soak
```

---

## Linting

```bash
ruff check app/
```

No project-specific linter config exists. CI runs `ruff check` and Bandit security scan (HIGH severity gate).

### Type Checking

CI runs **Pyright** in the `type-check` job (`pyright` at repo root after installing deps). Repo defaults are in `pyproject.toml` under `[tool.pyright]` (`typeCheckingMode = "off"`).

Locally:

```bash
pip install pyright
pyright
```

Use `from __future__ import annotations` at the top of new files for modern type hint syntax.

---

## Code Structure

```text
app/
├── _meta/              # App metadata (version, build info)
├── api/                # FastAPI routes and schemas
│   ├── routers/        # One module per domain
│   └── schemas/        # Request/response Pydantic models
├── core/               # Config, database, security, WebSocket, events, cache, redis
├── models/             # SQLAlchemy database models
├── repositories/       # Data access layer (Repository pattern)
├── services/
│   ├── ai/             # Agents, memory, knowledge facade, LLM glue (RAG engine is spectra_ai)
│   │   ├── agents/     # 12 specialized agents (scope → reporting)
│   │   ├── context.py  # Context window management (token budgeting)
│   │   ├── knowledge.py # RAG + methodology helpers (calls spectra_ai.rag)
│   │   ├── router.py   # TensorZero smart routing
│   │   ├── memory.py   # Persistent cross-mission learning
│   │   ├── playbook.py # Deterministic attack playbooks
│   │   ├── grounding.py # Anti-hallucination framework
│   │   └── cve_intel.py # CVE correlation database
│   ├── mission/        # Mission lifecycle, execution, exploitation
│   │   └── credentials.py # Per-mission credential store
│   ├── tools/          # Tool registry, adapter, parser, installer
│   │   └── sandbox/    # Per-mission sandbox pool management
│   ├── scaling/        # Server pool manager, load balancing
│   ├── gateway/        # Service registry, remote service adapters
│   ├── provisioning/   # SSH auto-provisioning for remote servers
│   └── shell/          # Reverse shell session management
└── utils/              # Shared utilities

packages/
├── common/             # spectra_common shared primitives
├── domain/             # spectra_domain integration contracts
└── tools-core/         # spectra_tools_core registry contracts

services/
├── api/                # `spectra_api` FastAPI bootstrap plus UI static/templates
├── ai/                 # spectra_ai: RAG, embeddings, LLM client, prompts (`services/ai/src/spectra_ai/`)
├── scheduler/          # spectra_scheduler background service entry point
└── worker/             # spectra_worker job queue consumer

docker/
├── compose.yaml             # Dev / test / targets via `--profile` (`app`, `test`, `targets`, …)
├── docker-compose.swarm.yml # Docker Swarm production stack
├── Caddyfile.prod           # Production Caddy config
├── targets/                 # Vulnerable test containers
├── Dockerfile.api           # API/UI image
├── Dockerfile.ai            # AI service image
├── Dockerfile.scheduler     # Scheduler service image
└── Dockerfile.worker        # Kali worker image

plugins/                     # Tool plugin JSON configs (26 included)
data/                        # Runtime data (cache, auth, missions, sessions)
tests/                       # Unit, integration, e2e tests
docs/                        # Documentation
config/                      # Build configs (tailwind, postcss)
```

---

## Key Conventions

- **Database**: PostgreSQL + pgvector, async via SQLAlchemy + asyncpg
- **Migrations**: Alembic — auto-run on startup via `scripts/start.sh`
- **Auth**: JWT tokens, HS256
- **Task queue**: PostgreSQL-backed job queue with LISTEN/NOTIFY
- **Config**: Pydantic Settings from environment variables + runtime overrides
- **Versioning**: CalVer (`YYYY.MM.DD[.patch]`)
- **Caching**: Dual-layer — PostgreSQL `CacheService` for persistent cache, Redis `RedisCache` for rate limiting and ephemeral data
- **Rate limiting**: Redis-backed distributed rate limiting (falls back to in-memory when Redis is unavailable)
- **Event delegation**: CSP-safe `data-action` / `data-on-submit` / `data-on-change` / `data-on-input` attributes (see [Frontend Patterns](frontend-patterns.md))
- **Design tokens**: CSS custom properties in `services/api/static/css/input.css` (see [Design Tokens](design-tokens.md))

---

## Docker Notes

- Docker socket (`/var/run/docker.sock`) is mounted read-only into the app container
- The app auto-runs Alembic migrations on startup
- Sandboxes use golden images built from `plugins/*.json`; leftover installs are on-demand when a tool runs
- `xhtml2pdf` requires system packages `libcairo2-dev`, `pkg-config`, `python3-dev`
- Adding a new `.json` file to `plugins/` is all that is needed for a new tool
- Human-in-the-loop tests: patch `settings.REQUIRE_APPROVAL` only when covering the env kill-switch branch

---

## Contributing

1. Fork the repository and create a feature branch
2. Install pre-commit hooks: `pre-commit install`
3. Follow existing code style (no specific linter config — use `ruff`)
4. Add tests for new functionality
5. Run `make check` (lint + import boundaries + unit tests)
6. If you changed templates or CSS, run `make css-build-prod`
7. Ensure `docker compose -f docker/compose.yaml --profile test run --rm settings-test-runner` passes (see CI)
8. Submit a PR to `main`
