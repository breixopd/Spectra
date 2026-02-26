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
| **tools** | `spectra-tools` (Kali Linux worker) | Security tool execution via Arq | Optional for basic UI testing |
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

Unit tests use mocks and do **not** require running Docker services:

```bash
python3 -m pytest tests/unit/ --no-cov -q
```

Integration tests under `tests/integration/` require live services (Redis, LLM, tools container). Expected failures when running outside Docker network:
- RAG tests need Redis Stack on `localhost:6379`
- LLM tests need a configured AI provider
- Real tool workflow tests need security tools (nmap, etc.) installed
- Tool execution tests need Docker socket access

To run only unit tests: `python3 -m pytest tests/unit/ --no-cov`

### Linting

No project-specific linter config exists. Use `ruff` for basic Python linting:

```bash
ruff check app/
```

### Key gotchas

- `.env.test` is loaded by `pytest-dotenv` via `pytest.ini`. It configures `DATABASE_URL` (SQLite/aiosqlite), `AI_PROVIDER=mock`, `FULLY_AUTOMATED=true`, and other test defaults.
- `pytest-asyncio` mode is `strict` — all async tests need `@pytest.mark.asyncio`.
- Docker socket (`/var/run/docker.sock`) is mounted read-only into containers.
- The app auto-runs Alembic migrations on startup via `scripts/start.sh`.
- In Docker-in-Docker environments, use `fuse-overlayfs` storage driver and `iptables-legacy`.
- Tool plugins auto-install in the tools container on startup. Adding a new `.json` file to `plugins/` is all that's needed.
- `FULLY_AUTOMATED=true` disables human approval requirements — tests that verify human approval behavior must monkeypatch this to `False`.
- `xhtml2pdf` (in `requirements-app.txt`) needs system packages `libcairo2-dev`, `pkg-config`, and `python3-dev` to build its `pycairo` transitive dependency. Install them with `apt-get` before `pip install -r requirements-app.txt` if they are missing.
