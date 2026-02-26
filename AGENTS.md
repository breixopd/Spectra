# Spectra - AI-Driven Security Assessment Platform

## Overview

Spectra is a Multi-Agent System (MAS) for automated security assessments built with FastAPI (Python 3.11+), PostgreSQL, Redis Stack, and Docker Compose. See `README.md` for full architecture and setup instructions.

## Cursor Cloud specific instructions

### Services

| Service | Container | Purpose | Required |
|---------|-----------|---------|----------|
| **db** | `spectra-db` (postgres:16-alpine) | Primary data store | Yes |
| **redis** | `spectra-redis` (redis/redis-stack) | Task queue, cache, vector store | Yes |
| **app** | `spectra-app` (FastAPI) | API + Web UI on port 5000 | Yes |
| **tools** | `spectra-tools` (Kali Linux worker) | Security tool execution | Optional for basic UI testing |
| **ai** | `spectra-ai` (Ollama) | Local LLM inference (needs GPU) | No - use `AI_PROVIDER=api` instead |

### Starting the application

Docker must be running first (`sudo dockerd` if not already started). Then:

```bash
cd /workspace/docker
docker compose up -d db redis    # Start infrastructure
docker compose build app         # Build app image (first time only)
docker compose up -d app         # Start the FastAPI app
```

The app is accessible at `http://localhost:5000`. On first run it redirects to `/setup` for admin user creation.

The Ollama AI service (`ai`) requires an NVIDIA GPU and is skipped in cloud agent environments. The tools worker (`tools`) is based on Kali Linux and is large; it's only needed for running actual security scans.

### Running tests

Unit/integration tests use mocks and do **not** require running Docker services:

```bash
cd /workspace
python3 -m pytest tests/unit/ -q
```

Note: Some tests have pre-existing Pydantic validation failures.

### Linting

No project-specific linter config exists. Use `ruff` for basic Python linting:

```bash
ruff check app/
```

### Key gotchas

- The `.env.test` file is loaded by `pytest-dotenv` via `pytest.ini`. It configures `DATABASE_URL` (SQLite/aiosqlite), `AI_PROVIDER=mock`, and other test defaults.
- `pytest-asyncio` mode is `strict` — all async tests need `@pytest.mark.asyncio`.
- Docker socket (`/var/run/docker.sock`) is mounted read-only into containers; ensure it exists before `docker compose up`.
- The app auto-runs Alembic migrations on startup via `scripts/start.sh`.
- In Docker-in-Docker environments, use `fuse-overlayfs` storage driver and `iptables-legacy`.
