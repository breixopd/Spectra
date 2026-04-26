<div align="center">

# Spectra

**AI-Driven Security Assessment Platform**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://docs.docker.com/compose/)
[![License: Private](https://img.shields.io/badge/License-Private-red.svg)]()

[📖 Wiki](docs/wiki/home.md) · [🚀 Quick Start](#quick-start) · [📡 API Reference](docs/wiki/api-reference.md) · [🤝 Contributing](CONTRIBUTING.md)

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
- **Free local embeddings** by default — fastembed with BAAI/bge-small-en-v1.5, no API key needed
- Lazy model download: embedding model is only fetched on first use, zero disk overhead when using an API provider
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
- S3-compatible storage with bundled Garage by default, plus AWS S3 and other compatible endpoints

### Security and Access Control

- JWT authentication with role-based access control (RBAC)
- Three roles: admin, operator, viewer
- Password reset flow (forgot-password → token → reset) with anti-enumeration
- Per-plan resource limits and rate limiting
- Audit trail for all administrative actions

### Reliability & Infrastructure

- **Dead-letter queue** — failed jobs retry 3x with backoff, then move to dead letter for admin review
- **Cleanup workers** — hourly automated cleanup of expired cache, orphaned sandboxes, and old jobs
- **WebSocket reconnection** — client-side exponential backoff (1s → 30s max, 10 retries)
- **DI container** — lightweight service container (`app/core/container.py`) for testable dependency injection
- **Notification jobs** — webhook delivery for mission completion, critical findings, and exploit success

## Documentation

The repo documentation is organized as a wiki under [docs/wiki/home.md](docs/wiki/home.md).

Start here:

- [Wiki Home](docs/wiki/home.md)
- [Deployment Guide](docs/wiki/deployment-guide.md)
- [Operations](docs/wiki/operations.md)
- [Configuration](docs/wiki/configuration.md)
- [Development](docs/wiki/development.md)
- [Ops Script Index](scripts/ops/README.md)
- [Microservices Split Notes](docs/wiki/microservices-split.md)

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

Open <http://localhost:5000> — on first run you'll be redirected to `/setup` to create your admin account.

### 4. Configure AI provider

In the setup wizard or admin panel, configure your LLM provider:

- **TensorZero Gateway**: Routes requests to any supported LLM provider (OpenAI, Anthropic, OpenRouter, etc.)
- **Configuration**: Set `TENSORZERO_GATEWAY_URL` to point to your TensorZero gateway instance

See [Getting Started](docs/wiki/development.md#getting-started) for detailed setup instructions.

## Configuration

Spectra is configured via environment variables in `.env`. Key settings:

| Variable                 | Description                         | Default                                                    |
| ------------------------ | ----------------------------------- | ---------------------------------------------------------- |
| `DATABASE_URL`           | PostgreSQL connection string        | `postgresql+asyncpg://spectra:spectra_dev@db:5432/spectra` |
| `TENSORZERO_GATEWAY_URL` | TensorZero gateway URL              | `""`                                                       |
| `LLM_TIMEOUT`            | LLM request timeout (seconds)       | `600`                                                      |
| `FULLY_AUTOMATED`        | Skip human approval for all actions | `false`                                                    |
| `JWT_SECRET_KEY`         | Secret key for JWT tokens           | (auto-generated)                                           |
| `PLUGIN_SAFE_MODE`       | Require signed plugins              | `true`                                                     |
| `EMBEDDING_MODEL`        | Embedding model for RAG             | `local/BAAI/bge-small-en-v1.5`                             |

See [Configuration Guide](docs/wiki/configuration.md) for the full reference.

## API Overview

All API endpoints are under `/api/v1/` with a deprecated alias at `/api/`.

| Endpoint Group | Path                | Description                       |
| -------------- | ------------------- | --------------------------------- |
| **Auth**       | `/api/v1/auth/`     | Login, token management, setup    |
| **Missions**   | `/api/v1/missions/` | Create, monitor, steer missions   |
| **Tools**      | `/api/v1/tools/`    | Tool registry, execution, plugins |
| **Findings**   | `/api/v1/findings/` | Security findings CRUD            |
| **Exploits**   | `/api/v1/exploits/` | Exploit attempt history           |
| **System**     | `/api/v1/system/`   | Health, status, operations        |
| **Admin**      | `/api/admin/`       | User/plan management, audit logs  |

Interactive API docs are available at `/docs` (Swagger UI) and `/redoc`.

## Development

### Local setup

```bash
# Install dependencies
pip install -r requirements/app.txt

# Set up environment
cp .env.example .env
# Edit .env with local database URL and TensorZero gateway settings

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --reload --port 5000
```

### Running tests

Create a local test env file once (not committed; contains optional API keys for live LLM tests):

```bash
cp .env.test.example .env.test
# Edit .env.test: set OPENAI_API_KEY (e.g. OpenRouter) for live model tests; leave empty for non-LLM runs.
# Embeddings default to local fastembed when EMBEDDING_API_KEY is empty.
```

```bash
# General unit tests
./scripts/test.sh unit

# Targeted settings/router/setup validation
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner

# Integration tests in Docker (may require live services)
./scripts/test.sh integration

# Live integration tests (requires live services)
./tests/run_live_tests.sh

# Burst/load and performance smoke harnesses
./tests/run_load_tests.sh load
./tests/run_load_tests.sh performance

# Mixed-traffic soak/stability harness
./tests/run_load_tests.sh soak
```

For the full test matrix and release-gate guidance, see [Testing Strategy](docs/wiki/testing-strategy.md). The committed live harness now covers direct app login and password-reset bursts, real Caddy edge throttling with opt-in recovery checks, WebSocket churn and message bursts, Redis-backed multi-replica limit sharing, concurrent worker-backed tool execution, moderate-concurrency route latency, PostgreSQL-backed queue drain throughput, and a first-pass mixed-traffic soak runner. Query benchmarks, queue retry and dead-letter profiling, and resource-ceiling automation still remain separate work.

### Linting

```bash
ruff check app/
```

## Documentation

Full documentation is in the [Wiki](docs/wiki/home.md):

| Topic            | Link                                                           |
| ---------------- | -------------------------------------------------------------- |
| Architecture     | [docs/wiki/architecture.md](docs/wiki/architecture.md)         |
| Configuration    | [docs/wiki/configuration.md](docs/wiki/configuration.md)       |
| Operations       | [docs/wiki/operations.md](docs/wiki/operations.md)             |
| Deployment       | [docs/wiki/deployment.md](docs/wiki/deployment.md)             |
| Scaling          | [docs/wiki/scaling.md](docs/wiki/scaling.md)                   |
| API Reference    | [docs/wiki/api-reference.md](docs/wiki/api-reference.md)       |
| Plugins          | [docs/wiki/plugins.md](docs/wiki/plugins.md)                   |
| Pentest Workflow | [docs/wiki/pentest-workflow.md](docs/wiki/pentest-workflow.md) |
| Sandboxes        | [docs/wiki/sandboxes.md](docs/wiki/sandboxes.md)               |
| Security         | [docs/wiki/security.md](docs/wiki/security.md)                 |
| Authentication   | [docs/wiki/authentication.md](docs/wiki/authentication.md)     |
| Worker System    | [docs/wiki/worker-system.md](docs/wiki/worker-system.md)       |
| Deployment Guide | [docs/wiki/deployment-guide.md](docs/wiki/deployment-guide.md) |
| Development      | [docs/wiki/development.md](docs/wiki/development.md)           |
| Testing Strategy | [docs/wiki/testing-strategy.md](docs/wiki/testing-strategy.md) |
| Ops Script Index | [scripts/ops/README.md](scripts/ops/README.md)                 |
| Roadmap          | [docs/wiki/roadmap.md](docs/wiki/roadmap.md)                   |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, testing requirements, and the pull request process.

## License

Private — All rights reserved.
