<div align="center">

# Spectra

**Autonomous Security Assessment Platform**

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/breixopd/Spectra/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Wiki](docs/wiki/Home.md) · [Quick Start](#quick-start) · [API Reference](docs/wiki/api-reference.md) · [Contributing](CONTRIBUTING.md)

</div>

---

## Overview

Spectra automates end-to-end penetration testing—from scoping through post-exploitation and reporting—using coordinated specialist agents, consensus voting on critical decisions, and human oversight where it matters. Methodology progress in the UI is driven by **YAML framework specs** (PTES, OWASP, NIST), not hardcoded phase lists.

## Key Features

### Mission execution

- **Dynamic pentest frameworks** — `ptes`, `owasp`, and `nist` loaded from YAML; phase timelines and milestones follow the active framework
- **Multi-agent planning and execution** — scope, tooling, exploitation, reporting, and post-exploitation specialists
- **Eight quality gates** — plan, tool selection, payload, replan, execution, plus output parsing, tool pick, and red-flag checks
- **Adaptive replanning** — strategy adjusts from findings without aborting the whole mission on a single tool failure

### Plugin-based tool system

- **32+ security tool plugins** (Nmap, Nuclei, SQLMap, Metasploit, and more) defined in JSON
- **Golden image pipeline** — tools baked into `spectra-tools:latest` for workers/sandboxes; on-demand install is fallback only
- Cryptographic signature verification for plugin integrity

### Knowledge and context

- RAG over CVE data and tool documentation (pgvector)
- **Local embeddings by default** — fastembed / BAAI/bge-small-en-v1.5 with lazy download when no API key is set
- Per-mission credential store and context budgeting to limit prompt growth

### Sandboxes and scale

- Per-mission Docker sandboxes with tiered resources and OOM escalation
- Multi-server pools, S3-compatible storage (Garage by default), dead-letter queue and cleanup workers
- Real-time dashboard (SSR + WebSocket), RBAC, audit logging

## Quick Start

### Prerequisites

- Docker and Docker Compose
- 4 GB+ RAM (8 GB+ recommended)
- Optional: NVIDIA GPU for local embeddings (API providers work without it)

### 1. Clone and configure

```bash
git clone https://github.com/breixopd/Spectra.git
cd Spectra
cp .env.example .env  # Edit with your settings
```

### 2. Start services

```bash
docker compose -f deploy/docker/compose.yaml --profile app up -d
```

### 3. Access the dashboard

Open <http://localhost:5000> (or the Caddy port shown by `scripts/first_run.sh`) — on first run you are redirected to `/setup`. Production-like setups require the one-time `SPECTRA_SETUP_TOKEN` enrollment token before an admin account can be created.

### 4. Configure the LLM gateway

In setup or the admin panel, set **`TENSORZERO_GATEWAY_URL`** to your TensorZero gateway (OpenAI, Anthropic, OpenRouter, etc.). See [Development](docs/wiki/development.md#getting-started).

## Configuration

Key environment variables (full list: [Configuration](docs/wiki/configuration.md)):

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://spectra:spectra_dev@db:5432/spectra` |
| `TENSORZERO_GATEWAY_URL` | TensorZero gateway URL | `""` |
| `LLM_TIMEOUT` | LLM request timeout (seconds) | `600` |
| `REQUIRE_APPROVAL` | Force approval for high-risk actions (env only) | `false` |
| `JWT_SECRET_KEY` | JWT signing secret | (auto-generated on first boot) |
| `EMBEDDING_MODEL` | Embedding model for RAG | `local/BAAI/bge-small-en-v1.5` |
| `SESSION_IDLE_TIMEOUT_MINUTES` | Session idle timeout | `1440` |

## API Overview

Versioned REST API under `/api/v1/`. Use `/api/healthz` for container liveness and
`/api/health/ready` for full dependency readiness.

| Group | Path | Description |
| ----- | ---- | ----------- |
| Auth | `/api/v1/auth/` | Login, tokens, setup |
| Missions | `/api/v1/missions/` | Create, monitor, steer missions |
| Tools | `/api/v1/tools/` | Registry, execution, plugins |
| Findings | `/api/v1/findings/` | Findings CRUD |
| Admin | `/api/admin/` | Users, plans, audit logs |

Interactive docs: `/docs` (Swagger), `/redoc`.

## Development

```bash
uv sync --all-packages --group dev
cp .env.example .env
alembic -c db/alembic.ini upgrade head
uvicorn spectra_api.main:app --reload --port 5000
```

### Tests

```bash
cp .env.test.example .env.test   # required for host pytest; optional API keys for live LLM tests
uv sync --all-packages --group dev
./scripts/test.sh unit
./scripts/test.sh integration    # Docker
```

Host pytest auto-loads `.env.test` via `env_files` in `pyproject.toml` (`[tool.pytest.ini_options]`).

See [Testing strategy](docs/wiki/testing-strategy.md) and [CI parity](docs/runbooks/ci-parity-local.md). Pull request CI runs **static-analysis** in Docker (Ruff, import boundaries, Pyright, Bandit).

```bash
ruff check packages/ services/
```

## Documentation

| Topic | Link |
| ----- | ---- |
| Wiki home | [docs/wiki/Home.md](docs/wiki/Home.md) · [GitHub Wiki](https://github.com/breixopd/Spectra/wiki) |
| Deployment (start here) | [docs/wiki/deployment-guide.md](docs/wiki/deployment-guide.md) |
| CI/CD and images | [docs/wiki/deployment.md](docs/wiki/deployment.md) |
| Operations | [docs/wiki/operations.md](docs/wiki/operations.md) |
| Architecture | [docs/wiki/architecture.md](docs/wiki/architecture.md) |
| Pentest workflow | [docs/wiki/pentest-workflow.md](docs/wiki/pentest-workflow.md) |
| Configuration | [docs/wiki/configuration.md](docs/wiki/configuration.md) |
| API reference | [docs/wiki/api-reference.md](docs/wiki/api-reference.md) |
| Plugins & golden image | [docs/wiki/plugins.md](docs/wiki/plugins.md) |
| Sandboxes | [docs/wiki/sandboxes.md](docs/wiki/sandboxes.md) |
| Worker system | [docs/wiki/worker-system.md](docs/wiki/worker-system.md) |
| Testing | [docs/wiki/testing-strategy.md](docs/wiki/testing-strategy.md) |
| Ops scripts | [scripts/ops/README.md](scripts/ops/README.md) |
| Runbooks | [docs/runbooks/README.md](docs/runbooks/README.md) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Spectra contributors.
