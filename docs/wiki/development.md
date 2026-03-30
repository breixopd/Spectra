# Development

[← Wiki Home](home.md) | [Operations](operations.md) | [Architecture](architecture.md) | [Plugins](plugins.md)

---

Local development setup, testing, code structure, and contributing guidelines.

## Getting Started

### Prerequisites

- Docker Engine 24.0+ and Docker Compose v2.20+
- Python 3.11+ (for local linting/development only — app runs in Docker)
- Git

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

The tools container auto-installs security tools on first boot.

### Local Ops Scripts

For local admin and troubleshooting work, use [Operations](operations.md) as the canonical runbook owner and [scripts/ops/README.md](../../scripts/ops/README.md) for the script-by-script index. The helper scripts default to the standard `spectra-*` container names, which matches the local Docker Compose setup.

---

## Testing

Docker/containerized test paths are the default for CI-grade verification, and targeted local pytest commands are also supported for faster developer iteration.

For the platform-wide verification matrix, release gate, and gaps between current automation and required future harnesses, see [Testing Strategy](testing-strategy.md).

### Settings/Router/Setup Validation

The targeted test suite for the settings, router, and setup workflow:

```bash
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner
```

Runs: `test_runtime_settings.py`, `test_system_setup.py`, `test_smart_router.py`, `test_settings_runtime_api.py`, `test_settings_templates.py`.

### Containerized Fallback

If the shared Compose test stack hits a network/subnet conflict, this fallback provides a containerized full unit suite run rather than the targeted settings/router/setup suite:

```bash
docker build -f docker/Dockerfile.tools -t spectra-tools-test .
docker run --rm \
  -e DATABASE_URL=sqlite+aiosqlite:///test.db \
  -e TENSORZERO_GATEWAY_URL=http://tensorzero:3000 \
  -e JWT_SECRET_KEY=test-secret-key \
  -e FULLY_AUTOMATED=true \
  -e PLUGIN_SAFE_MODE=false \
  -v "$PWD/app:/app/app:ro" \
  -v "$PWD/tests:/app/tests:ro" \
  -v "$PWD/pyproject.toml:/app/pyproject.toml:ro" \
  -v "$PWD/.env.test:/app/.env.test:ro" \
  -v "$PWD/alembic:/app/alembic:ro" \
  -v "$PWD/config/alembic.ini:/app/config/alembic.ini:ro" \
  -v "$PWD/plugins:/app/plugins:ro" \
  -v "$PWD/data:/app/data" \
  --entrypoint sh spectra-tools-test \
  -c "pip install -q pytest pytest-asyncio pytest-dotenv aiosqlite aiohttp httpx && python3 -m pytest tests/unit/ -q --override-ini=addopts="
```

### Non-live integration tests

Run non-live integration tests locally with this selector:

```bash
python3 -m pytest tests/integration/ -v --tb=short --timeout=120 -k "not live and not e2e"
```

For the Docker integration wrapper, which may require live services depending on the covered paths:

```bash
./scripts/test.sh integration
```

### Live Integration Tests

Use the explicit live integration harness when you need real-service coverage (PostgreSQL, LLM, tools container):

```bash
./tests/run_live_tests.sh
```

### UI Tests

Browser-based tests via Playwright:

```bash
./tests/run_ui_tests.sh
```

### Load And Performance Harnesses

First-pass load and performance coverage runs against the Docker test stack with a real Redis-backed app limiter and a dedicated Caddy test proxy.

```bash
# Burst and rate-limit coverage
./tests/run_load_tests.sh load

# Performance smoke coverage, including queue throughput
./tests/run_load_tests.sh performance

# Makefile wrappers
make test-load
make test-performance
```

This batch covers direct app login burst behavior, direct public registration burst behavior, real Caddy edge throttling, moderate-concurrency latency smoke for core routes, and PostgreSQL-backed queue drain throughput. Soak, WebSocket churn, and multi-replica rate-limit validation remain out of scope.

### Test Targets

Custom vulnerable containers for live testing:

```bash
# Standalone targets (difficulty-based)
cd docker/targets
docker compose -f docker-compose.targets.yml up -d

# Or use the test compose with --profile targets (vuln-web, vuln-ssh, vuln-network)
docker compose -f docker/docker-compose.test.yml --profile targets up -d
```

| Target | Difficulty | Services | Key Vulns |
| -------- | ----------- | ---------- | ----------- |
| Easy Web | Easy | HTTP, SSH | Default creds, phpinfo, directory listing |
| Medium Multi | Medium | HTTP, FTP, MySQL, SSH | FTP anon, LFI, weak DB creds |
| Hard Hardened | Hard | HTTPS API, SSH | CORS, SSRF, hidden endpoints, weak JWT |
| DVWA | Easy | HTTP | Classic web vulns (SQLi, XSS, etc.) |
| Juice Shop | Medium | HTTP | OWASP Top 10 |

### Test Configuration

- `.env.test` is loaded by `pytest-dotenv` via `pyproject.toml`
- `pytest-asyncio` mode is `strict` — all async tests need `@pytest.mark.asyncio`
- `DATABASE_URL` is configured via `.env.test` for the shared test database
- `TENSORZERO_GATEWAY_URL` points to the TensorZero gateway for LLM routing
- `FULLY_AUTOMATED=true` disables human approval requirements

---

## Linting

```bash
ruff check app/
```

No project-specific linter config exists. CI runs `ruff check` and Bandit security scan (HIGH severity gate).

---

## Code Structure

```text
app/
├── api/              # FastAPI routes and schemas
├── core/             # Config, database, security, WebSocket, events
├── models/           # SQLAlchemy database models
├── services/
│   ├── ai/           # LLM clients, agents, consensus, memory, playbooks
│   │   ├── agents/   # 12 specialized agents (scope → reporting)
│   │   ├── context.py # Context window management (token budgeting)
│   │   ├── rag.py    # PostgreSQL-backed RAG engine
│   │   ├── embeddings.py # Embedding service
│   │   ├── router.py # TensorZero smart routing
│   │   ├── memory.py # Persistent cross-mission learning
│   │   ├── playbook.py # Deterministic attack playbooks
│   │   ├── grounding.py # Anti-hallucination framework
│   │   └── cve_intel.py # CVE correlation database
│   ├── mission/      # Mission lifecycle, execution, exploitation
│   │   └── credentials.py # Per-mission credential store
│   ├── tools/        # Tool registry, adapter, parser, installer
│   │   └── sandbox/  # Per-mission sandbox pool management
│   ├── scaling/      # Server pool manager, load balancing
│   ├── gateway/      # Service registry, remote service adapters
│   ├── provisioning/ # SSH auto-provisioning for remote servers
│   └── shell/        # Reverse shell session management
├── templates/        # Jinja2 HTML templates
└── static/           # JavaScript and CSS

docker/
├── docker-compose.yml       # Dev stack (app, db, tools)
├── docker-compose.swarm.yml # Multi-host production (Docker Swarm)
├── docker-compose.test.yml  # Test runner
├── Caddyfile.prod           # Production Caddy config
├── targets/                 # Vulnerable test containers
├── Dockerfile.app           # FastAPI app image
└── Dockerfile.tools         # Kali tools worker image

plugins/                     # Tool plugin JSON configs (25+ included)
data/                        # Runtime data (cache, auth, missions, sessions)
tests/                       # Unit, integration, e2e tests
docs/                        # Documentation
```

---

## Key Conventions

- **Database**: PostgreSQL + pgvector, async via SQLAlchemy + asyncpg
- **Migrations**: Alembic — auto-run on startup via `scripts/start.sh`
- **Auth**: JWT tokens, HS256
- **Task queue**: PostgreSQL-backed job queue with LISTEN/NOTIFY
- **Config**: Pydantic Settings from environment variables + runtime overrides
- **Versioning**: CalVer (`YYYY.MM.DD[.patch]`)

---

## Docker Notes

- Docker socket (`/var/run/docker.sock`) is mounted read-only into the app container
- The app auto-runs Alembic migrations on startup
- Tool plugins auto-install in sandbox containers on first boot
- `xhtml2pdf` requires system packages `libcairo2-dev`, `pkg-config`, `python3-dev`
- Adding a new `.json` file to `plugins/` is all that's needed for a new tool
- `FULLY_AUTOMATED=true` in tests — monkeypatch to `False` for human approval tests

---

## Contributing

1. Fork the repository and create a feature branch
2. Follow existing code style (no specific linter config — use `ruff`)
3. Add tests for new functionality
4. Ensure `docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner` passes
5. Submit a PR to `main`
