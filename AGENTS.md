# Spectra - AI-Driven Security Assessment Platform

## Overview

Spectra is a Multi-Agent System (MAS) for automated security assessments built with FastAPI (Python 3.11+), PostgreSQL, and Docker Compose. See `README.md` for full architecture and setup instructions.

## Cursor Cloud specific instructions

### Services

| Service   | Container                           | Purpose                               | Required                           |
| --------- | ----------------------------------- | ------------------------------------- | ---------------------------------- |
| **db**    | `spectra-db` (pgvector/pgvector:pg16) | Primary data store, cache, task queue | Yes                                |
| **app**   | `spectra-app` (FastAPI)             | API + Web UI on port 5000             | Yes                                |
| **tools** | `spectra-tools` (Kali Linux worker) | Security tool execution               | Optional for basic UI testing      |
| **ai**    | `spectra-ai` (Ollama)               | Local LLM inference (needs GPU)       | No - use `AI_PROVIDER=api` instead |

> **Remote service gateways:** LLM and Sandbox services can each be routed to remote servers via `LLM_GATEWAY_URL` and `SANDBOX_ORCHESTRATOR_URL`. When set, in-process implementations are replaced by HTTP gateway clients transparently. See `app/services/gateway/service_registry.py`.

### Starting the application

Docker must be running first (`sudo dockerd` if not already started). In Docker-in-Docker environments, you may need to fix cgroups first — see Key gotchas below.

The full startup sequence:

```bash
# 1. Create network and start infrastructure
docker network create spectra-network 2>/dev/null || true
docker run -d --name spectra-db --network spectra-network \
  -e POSTGRES_USER=spectra -e POSTGRES_PASSWORD=spectra_dev -e POSTGRES_DB=spectra \
  pgvector/pgvector:pg16

# 2. Add network aliases (start.sh expects hostname "db")
docker network connect --alias db spectra-network spectra-db 2>/dev/null || true

# 3. Build and start the app
cd /workspace
docker build -f docker/Dockerfile.app -t spectra-app .
docker run -d --name spectra-app --network spectra-network -p 5000:5000 \
  --env-file .env \
  -e DATABASE_URL=postgresql+asyncpg://spectra:spectra_dev@db:5432/spectra \
  -e TOOL_CONTAINER_NAME=spectra-tools -e CONNECT_BACK_HOST=spectra-app \
  -v $(pwd)/app:/app/app -v $(pwd)/plugins:/app/plugins \
  -v $(pwd)/scripts:/app/scripts:ro -v $(pwd)/alembic:/app/alembic \
  -v $(pwd)/alembic.ini:/app/alembic.ini \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  spectra-app
```

The app is accessible at `http://localhost:5000`. On first run it redirects to `/setup` for admin user creation.

> **Multi-server deployment:** To route services to remote servers, set gateway URLs in `.env` before starting (`LLM_GATEWAY_URL`, `SANDBOX_ORCHESTRATOR_URL`), or configure them at runtime via the setup wizard or admin panel → Services tab.

The Ollama AI service (`ai`) requires an NVIDIA GPU and is skipped in cloud agent environments. The tools worker (`tools`) is based on Kali Linux and is large; it's only needed for running actual security scans.

### Running tests

Use Docker-only validation paths for this repo. For the settings/router/setup workflow, run the targeted containerized suite:

```bash
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner
```

Integration tests under `tests/integration/` require live services (PostgreSQL, LLM, tools container). Expected failures when running outside Docker network:

- RAG tests need PostgreSQL
- LLM tests need a configured AI provider
- Real tool workflow tests need security tools (nmap, etc.) installed
- Tool execution tests need Docker socket access

For live integration coverage, use `./tests/run_live_tests.sh`. For browser coverage, use `./tests/run_ui_tests.sh`.

If `docker/docker-compose.test.yml` hits a local subnet conflict, fall back to a containerized one-off runner instead of host-local pytest:

```bash
docker build -f docker/Dockerfile.tools -t spectra-tools-test .
docker run --rm \
  -e DATABASE_URL=sqlite+aiosqlite:///test.db \
  -e AI_PROVIDER=mock \
  -e JWT_SECRET_KEY=test-secret-key \
  -e FULLY_AUTOMATED=true \
  -e PLUGIN_SAFE_MODE=false \
  -v "$PWD/app:/app/app:ro" \
  -v "$PWD/tests:/app/tests:ro" \
  -v "$PWD/pytest.ini:/app/pytest.ini:ro" \
  -v "$PWD/.env.test:/app/.env.test:ro" \
  -v "$PWD/alembic:/app/alembic:ro" \
  -v "$PWD/alembic.ini:/app/alembic.ini:ro" \
  -v "$PWD/plugins:/app/plugins:ro" \
  -v "$PWD/data:/app/data" \
  --entrypoint sh spectra-tools-test \
  -c "pip install -q pytest pytest-asyncio pytest-dotenv aiosqlite aiohttp httpx && python3 -m pytest tests/unit/test_runtime_settings.py tests/unit/test_system_setup.py tests/unit/test_smart_router.py tests/unit/test_settings_runtime_api.py tests/unit/test_settings_templates.py -q --override-ini=addopts="
```

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
- In Docker-in-Docker environments, use `fuse-overlayfs` storage driver and `iptables-legacy`. You must also fix cgroupv2: move all root cgroup processes to an `init` sub-cgroup (`mkdir -p /sys/fs/cgroup/init && cat /sys/fs/cgroup/cgroup.procs | xargs -rn1 -I{} sh -c 'echo {} > /sys/fs/cgroup/init/cgroup.procs 2>/dev/null || true'`) **before** starting `dockerd`, otherwise containers fail with "cannot enter cgroupv2 ... invalid state".
- Tool plugins auto-install in the tools container on startup. Adding a new `.json` file to `plugins/` is all that's needed.
- `FULLY_AUTOMATED=true` disables human approval requirements — tests that verify human approval behavior must monkeypatch this to `False`.
- `xhtml2pdf` (in `requirements-app.txt`) needs system packages `libcairo2-dev`, `pkg-config`, and `python3-dev` to build its `pycairo` transitive dependency. Install them with `apt-get` before `pip install -r requirements-app.txt` if they are missing.
