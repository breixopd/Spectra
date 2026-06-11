# Development

[← Wiki Home](Home.md) | [Architecture](architecture.md) | [Frontend Patterns](frontend-patterns.md) | [Design Tokens](design-tokens.md) | [Operations](operations.md) | [Plugins](plugins.md)

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

docker compose -f deploy/docker/compose.yaml up -d
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

### Remote MCP over SSH (optional)

If your editor loads MCP servers from a user config file, you can run a stdio MCP server on another machine (code search, docs, etc.) and bridge it with SSH. Exact config path depends on the product; keep secrets out of the repo. Example skeleton: [`docs/examples/remote-mcp-ssh-bridge.example.json`](../examples/remote-mcp-ssh-bridge.example.json) — substitute SSH identity, host, checkout path, and the remote executable you run.

---

## Testing

### Host pytest (local, without Docker test runner)

```bash
cp .env.test.example .env.test
uv sync --all-packages --group dev
pytest tests/unit/ -q
```

Pytest auto-loads `.env.test` via `env_files` in `pyproject.toml` (`[tool.pytest.ini_options]`). Add optional API keys in `.env.test` for live LLM tests.

### Docker / CI test commands

The primary CI test command is:

```bash
docker compose -f deploy/docker/compose.yaml --profile test run --rm settings-test-runner
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

## Linting and static analysis

```bash
ruff check packages/ services/
```

CI runs one **`static-analysis`** job (`.github/workflows/ci.yml`): a single `Dockerfile.test` build, then Ruff, the import-boundary script, Pyright, and Bandit (HIGH severity / confidence gate). Ruff and Pyright defaults live in `pyproject.toml`.

### Type checking (Pyright)

Same **`static-analysis`** job installs Pyright in the test image and runs `pyright`. Repo defaults are under `[tool.pyright]` (`typeCheckingMode = "off"`).

Locally:

```bash
pip install pyright
pyright
```

Use `from __future__ import annotations` at the top of new files for modern type hint syntax.

---

## Code Structure

```text
packages/
├── common/             # spectra_common — config, encryption, constants, version metadata
├── auth/               # spectra_auth — service auth helpers
├── persistence/        # spectra_persistence — database, ORM models, repositories
├── mission/            # spectra_mission — FSM, frameworks, credentials, lifecycle
├── tools/              # spectra_tools — registry, adapters, sandbox pool, golden image
├── ai-core/            # spectra_ai_core — agents, memory, router, gateway, RAG facade
├── scaling/            # spectra_scaling — server pool, auto-scaler, resource manager
├── billing/            # spectra_billing
├── system/             # spectra_system — runtime settings, health
├── infrastructure/     # spectra_infra — queue, events, cache, redis, background tasks
├── observability/      # spectra_observability
├── domain/             # spectra_domain — integration contracts and DTOs
├── contracts/          # spectra_contracts
├── tools-core/         # spectra_tools_core — tool registry contracts
└── storage-policy/     # spectra_storage_policy

services/
├── api/                # spectra_api — FastAPI bootstrap, routers, UI static/templates
├── ai/                 # spectra_ai — RAG engine, embeddings, HTTP entry (`services/ai/src/spectra_ai/`)
├── scheduler/          # spectra_scheduler — background loops
└── worker/             # spectra_worker — job queue consumer

apps/web/               # React SPA

deploy/docker/
├── compose.yaml             # Dev / test / targets via `--profile` (`app`, `test`, `targets`, …)
├── docker-compose.swarm.yml # Docker Swarm production stack
├── Caddyfile.prod           # Production Caddy config
├── targets/                 # Vulnerable test containers
├── Dockerfile.api           # API/UI image
├── Dockerfile.ai            # AI service image
├── Dockerfile.scheduler     # Scheduler service image
└── Dockerfile.worker        # Kali worker image

db/alembic/               # Database migrations
plugins/                  # Tool plugin JSON configs
data/                     # Gitignored on host when used (local keys/cache); containers use /app/data
tests/                    # Unit, integration, e2e tests
docs/                     # Documentation
config/                   # Build configs (tailwind, postcss)
```

---

## Key Conventions

- **Database**: PostgreSQL + pgvector, async via SQLAlchemy + asyncpg
- **Migrations**: Alembic (`db/alembic/`) — auto-run on startup via `scripts/start.sh`
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
7. Ensure `docker compose -f deploy/docker/compose.yaml --profile test run --rm settings-test-runner` passes (see CI)
8. Submit a PR to `main`
