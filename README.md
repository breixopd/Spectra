<div align="center">

# Spectra

**AI-Driven Security Assessment Platform**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://docs.docker.com/compose/)
[![License: Private](https://img.shields.io/badge/License-Private-red.svg)]()

[📖 Documentation](docs/wiki/home.md) · [🚀 Quick Start](#quick-start) · [📡 API Reference](docs/wiki/api-reference.md) · [🤝 Contributing](CONTRIBUTING.md)

</div>

---

## Overview

Spectra is a Multi-Agent System (MAS) for automated security assessments. It coordinates 12 specialized AI agents to perform end-to-end penetration testing — from reconnaissance to reporting — with human oversight at every step.

Built on the PTES (Penetration Testing Execution Standard) methodology, Spectra automates the tedious and repetitive aspects of security assessments while keeping humans in control of critical decisions through a multi-agent consensus system.

## Key Features

### Multi-Agent AI System
- **12 specialized agents** — scope analysis, tool selection, exploitation, reporting, and more
- **K-threshold consensus voting** — critical decisions require agreement from multiple agents
- **5 quality gates** ensure decisions are validated before execution
- **Adaptive replanning** — agents autonomously adjust strategy based on findings

### Plugin-Based Tool System
- **26 security tools** out of the box (Nmap, Nuclei, SQLMap, Metasploit, etc.)
- JSON-defined plugin configurations — add new tools without code changes
- Cryptographic signature verification for plugin integrity
- Auto-installation and status tracking in isolated containers

### RAG Knowledge Base
- Contextual retrieval from CVE databases and tool documentation
- Past assessment knowledge reuse via pgvector embeddings
- Exploit database integration with searchable indices

### Per-Mission Sandboxes
- Isolated Docker containers with resource limits and network isolation
- Tiered resource allocation (basic, standard, enhanced, maximum)
- OOM-triggered automatic tier escalation
- Heartbeat monitoring with automatic cleanup

### Real-Time Dashboard
- Live mission monitoring with WebSocket updates
- Tool management, installation, and status tracking
- Admin panel with user/plan/server management
- Audit logging for compliance

### Multi-Server Scaling
- Server pool management with health monitoring
- Remote server provisioning via SSH
- Load balancing with weighted node selection
- S3-compatible storage (MinIO) with local filesystem fallback

### Security and Access Control
- JWT authentication with role-based access control (RBAC)
- Three roles: admin, operator, viewer
- Per-plan resource limits and rate limiting
- Audit trail for all administrative actions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Caddy (TLS)                          │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                     FastAPI App (:5000)                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐  │
│  │ REST API │  │ WebSocket │  │  Web UI  │  │   Admin   │  │
│  └────┬─────┘  └─────┬─────┘  └────┬─────┘  └─────┬─────┘  │
│       └───────┬───────┴─────────────┴──────────────┘        │
│               │                                              │
│  ┌────────────▼─────────────────────────────────────────┐   │
│  │              Service Layer                            │   │
│  │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐  │   │
│  │  │   AI    │ │ Mission  │ │  Tools  │ │ Storage  │  │   │
│  │  │ Agents  │ │ Manager  │ │ Service │ │ Service  │  │   │
│  │  └────┬────┘ └────┬─────┘ └────┬────┘ └────┬─────┘  │   │
│  │       │           │            │            │         │   │
│  │  ┌────▼────┐ ┌────▼─────┐ ┌───▼────┐  ┌───▼─────┐  │   │
│  │  │   LLM  │ │  State   │ │ Plugin │  │  MinIO  │  │   │
│  │  │ Router │ │ Machine  │ │Registry│  │   / S3  │  │   │
│  │  └────────┘ └──────────┘ └────────┘  └─────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
    │  PostgreSQL +  │ │  Kali    │ │   Ollama   │
    │   pgvector     │ │  Tools   │ │  (GPU/API) │
    │                │ │  Worker  │ │            │
    └────────────────┘ └──────────┘ └────────────┘
```

### Services

| Service | Container | Purpose |
|---------|-----------|---------|
| **db** | PostgreSQL 16 + pgvector | Primary data store, vector search, job queue, cache |
| **app** | FastAPI (Python 3.11) | API server + Web UI (port 5000) |
| **tools** | Kali Linux worker | Security tool execution in isolated environment |
| **minio** | MinIO | S3-compatible object storage for mission data |
| **caddy** | Caddy | Reverse proxy, automatic TLS termination |
| **ai** | Ollama (optional) | Local LLM inference (requires GPU) |

### AI Agents

| Agent | Responsibility |
|-------|---------------|
| **Scope** | Analyze targets, define assessment boundaries |
| **Tool Selector** | Choose optimal tools for each task |
| **Mission Controller** | Plan assessment phases and task ordering |
| **Safety Supervisor** | Enforce scope limits, block dangerous actions |
| **Exploit Crafter** | Generate and refine exploitation scripts |
| **Reporter** | Produce findings reports with remediation advice |
| **Debrief** | Summarize completed missions |
| **CVE Intel** | Enrich findings with CVE/vulnerability data |
| **Consensus** | Coordinate multi-agent voting on decisions |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- 4 GB+ RAM (8 GB+ recommended)
- For local AI: NVIDIA GPU + CUDA drivers (optional — can use API providers)

### 1. Clone and configure

```bash
git clone https://github.com/breixopd14/spectra.git
cd spectra
cp .env.example .env  # Edit with your settings
```

### 2. Start services

```bash
docker compose -f docker/docker-compose.yml up -d
```

### 3. Access the dashboard

Open http://localhost:5000 — on first run you'll be redirected to `/setup` to create your admin account.

### 4. Configure AI provider

In the setup wizard or admin panel, configure your LLM provider:
- **API providers**: OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint
- **Local inference**: Ollama (requires GPU)
- **Remote gateway**: Point to a remote Spectra LLM gateway

See [Getting Started](docs/wiki/development.md#getting-started) for detailed setup instructions.

## Configuration

Spectra is configured via environment variables in `.env`. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://spectra:spectra_dev@db:5432/spectra` |
| `AI_PROVIDER` | LLM provider (`openai`, `anthropic`, `ollama`, `openrouter`) | `openai` |
| `AI_MODEL` | Model name | `gpt-4o` |
| `FULLY_AUTOMATED` | Skip human approval for all actions | `false` |
| `JWT_SECRET_KEY` | Secret key for JWT tokens | (generated on setup) |
| `PLUGIN_SAFE_MODE` | Require signed plugins | `true` |
| `LLM_GATEWAY_URL` | Remote LLM gateway URL | — |
| `SANDBOX_ORCHESTRATOR_URL` | Remote sandbox orchestrator URL | — |

See [Configuration Guide](docs/wiki/configuration.md) for the full reference.

## API Overview

All API endpoints are under `/api/v1/` with a deprecated alias at `/api/`.

| Endpoint Group | Path | Description |
|---------------|------|-------------|
| **Auth** | `/api/v1/auth/` | Login, token management, setup |
| **Missions** | `/api/v1/missions/` | Create, monitor, steer missions |
| **Tools** | `/api/v1/tools/` | Tool registry, execution, plugins |
| **Findings** | `/api/v1/findings/` | Security findings CRUD |
| **Exploits** | `/api/v1/exploits/` | Exploit attempt history |
| **System** | `/api/v1/system/` | Health, status, operations |
| **Admin** | `/api/admin/` | User/plan management, audit logs |

Interactive API docs are available at `/docs` (Swagger UI) and `/redoc`.

## Project Structure

```
spectra/
├── app/                    # Application code
│   ├── api/                # FastAPI routers and schemas
│   │   ├── routers/        # Route handlers (admin, auth, missions, tools, ...)
│   │   └── schemas.py      # Pydantic request/response models
│   ├── core/               # Infrastructure (config, DB, security, cache, events)
│   ├── models/             # SQLAlchemy ORM models
│   ├── repositories/       # Data access layer (Repository pattern)
│   ├── services/           # Business logic
│   │   ├── ai/             # LLM clients, agents, consensus, RAG
│   │   ├── mission/        # Mission lifecycle, execution, steering
│   │   ├── tools/          # Tool registry, adapters, sandboxes
│   │   └── ...             # Billing, email, gateway, storage, scaling
│   ├── templates/          # Jinja2 HTML templates
│   ├── static/             # CSS, JS, images
│   └── worker/             # Tools container job queue worker
├── plugins/                # Security tool plugin definitions (JSON)
├── alembic/                # Database migrations
├── docker/                 # Dockerfiles and Compose configs
├── tests/                  # Unit, integration, and E2E tests
├── docs/                   # Documentation wiki
└── scripts/                # Utility scripts (setup, benchmarks, etc.)
```

## Development

### Local setup

```bash
# Install dependencies
pip install -r requirements-app.txt

# Set up environment
cp .env.example .env
# Edit .env with local database URL and AI provider settings

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --reload --port 5000
```

### Running tests

```bash
# Unit tests (containerized, recommended)
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner

# Or run directly with pytest
pytest tests/unit/ -q

# Integration tests (requires live services)
./tests/run_live_tests.sh
```

### Linting

```bash
ruff check app/
```

## Documentation

Full documentation is in the [Wiki](docs/wiki/home.md):

| Topic | Link |
|-------|------|
| Architecture | [docs/wiki/architecture.md](docs/wiki/architecture.md) |
| Configuration | [docs/wiki/configuration.md](docs/wiki/configuration.md) |
| Deployment | [docs/wiki/deployment.md](docs/wiki/deployment.md) |
| Scaling | [docs/wiki/scaling.md](docs/wiki/scaling.md) |
| API Reference | [docs/wiki/api-reference.md](docs/wiki/api-reference.md) |
| Plugins | [docs/wiki/plugins.md](docs/wiki/plugins.md) |
| Pentest Workflow | [docs/wiki/pentest-workflow.md](docs/wiki/pentest-workflow.md) |
| Sandboxes | [docs/wiki/sandboxes.md](docs/wiki/sandboxes.md) |
| Security | [docs/wiki/security.md](docs/wiki/security.md) |
| Development | [docs/wiki/development.md](docs/wiki/development.md) |
| Roadmap | [docs/wiki/roadmap.md](docs/wiki/roadmap.md) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, testing requirements, and the pull request process.

## License

Private — All rights reserved.
