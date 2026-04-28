# AGENTS.md

## Project

Spectra is a Docker-first FastAPI security assessment platform with separate runtime roles:

- API/UI: FastAPI routes, templates, static assets, auth, billing, admin, migrations.
- AI service: LLM routing, RAG, TensorZero/OpenRouter integration, mission intelligence.
- Scheduler: maintenance, scaling, image updates, deployment orchestration.
- Worker (`services/worker/src/spectra_worker/`): Kali-based tools runtime, plugins, sandbox execution, target-network access.
- Infrastructure: Postgres/pgvector, Redis, Garage S3, ClickHouse, TensorZero, Caddy.

## Rules for Agents

- Use Docker for tests and live validation. Do not run full pytest, integration, E2E, or deployment workflows on the host when Docker paths exist.
- Prefer `docker/compose.yaml` for Compose and `.github/workflows/ci.yml` for CI parity.
- Treat `docker/docker-compose.swarm.yml` as production deployment shape. Production secrets belong in Swarm secrets and `*_FILE` variables.
- Keep service boundaries clean. Do not make API/UI code a dependency of AI, scheduler, or worker.
- If shared behavior is used by multiple services, put it in an explicit shared package instead of copying a broad tree into each image.
- Do not revert unrelated working-tree changes.
## Useful Tools

- **Chunkhound MCP:** Cursor reads **user-level** MCP config (`~/.cursor/mcp.json`), not the repo — `.cursor/` is gitignored. Copy `docs/examples/cursor-chunkhound-mcp.json` to `~/.cursor/mcp.json`, replace placeholders (`USER@YOUR_VPS_HOST`, paths), and ensure SSH keys allow non-interactive login. Running Chunkhound on the VPS keeps indexing off the developer machine; the remote DB path is typically `.chunkhound/chunks.duckdb` under the clone.
- Browser MCP: use for deployed UI testing and browser CPU profiling.
- Docker commands: use for tests, image builds, Compose/Swarm validation, container stats, image history, and live service verification.
- `gh`: use for GitHub CI status, runs, logs, checks, PRs, and workflow investigation.

## Verification Expectations

- CI-equivalent Docker lint/unit/integration/security/build checks.
- Actual app services started from built images without source bind mounts.
- Live mission smoke against safe Docker targets.
- Playwright/browser coverage for setup, login, dashboard, mission start/status, privacy controls, admin, billing/plan paths, settings, and docs/help pages.
- Scaling and maintenance exercised through scheduler/scaling services.
- Image size and runtime resource reports captured before optimization decisions.

## Secrets

Never commit `.env`, `.env.test`, generated secret files, private keys, tokens, or VPS credentials. If credentials appear in chat or logs, recommend rotation after work.

