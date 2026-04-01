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

The primary CI test command is:

```bash
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner
```

For local iteration, run unit tests directly:

```bash
python3 -m pytest tests/unit/ -q
```

For the full verification matrix, release gate criteria, load/performance/soak harnesses, and known gaps, see [Testing Strategy](testing-strategy.md).

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
