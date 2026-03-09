# Spectra Deployment Guide

## Overview

Spectra uses Docker Compose for deployment with a CI/CD pipeline via GitHub Actions.
Images are pushed to GitHub Container Registry (GHCR) and deployed automatically
on release.

## Architecture

| Service   | Image                              | Purpose                                              |
| --------- | ---------------------------------- | ---------------------------------------------------- |
| **db**    | `postgres:16-alpine`               | PostgreSQL database (data, cache, queues, RAG)       |
| **caddy** | `caddy:2-alpine`                   | Reverse proxy — TLS, security headers, rate limiting |
| **app**   | `ghcr.io/breixopd14/spectra-app`   | FastAPI backend (internal port 5000)                 |
| **tools** | `ghcr.io/breixopd14/spectra-tools` | Kali Linux security worker                           |

In production, Caddy sits in front of the app. External traffic hits Caddy (port 443 by default);
Caddy proxies to the app container on port 5000 internally. The app container does **not**
expose a public port in the production compose file.

## Prerequisites

- Docker Engine 24.0+ and Docker Compose v2.20+
- A server with at least 4 CPU cores, 8 GB RAM, 50 GB disk
- A domain name pointed at the server (for automatic TLS via Let's Encrypt)

## Versioning

Spectra uses **CalVer** (date-based versioning): `YYYY.MM.DD[.patch]`

Examples: `2026.03.07`, `2026.03.07.1`

Generate the current version locally:

```bash
python version.py                # 2026.03.07
python version.py --patch 1      # 2026.03.07.1
```

---

## CI/CD Pipeline

Two workflow files in `.github/workflows/`:

### `ci.yml` — Continuous Integration

Triggered on every push/PR to `main` or `develop`.

| Job          | Purpose                                                                                                     |
| ------------ | ----------------------------------------------------------------------------------------------------------- |
| **lint**     | `ruff check` on app code                                                                                    |
| **test**     | Containerized validation (`docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner`) |
| **security** | Bandit security scan (HIGH severity gate)                                                                   |
| **deps**     | Dependency audit                                                                                            |

For operator validation of the settings/router/setup flow, use the targeted Docker command instead of host-local pytest:

```bash
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner
```

If the shared test compose network collides with a local subnet, use the containerized fallback documented in `README.md` and `AGENTS.md` rather than switching back to local Python.

### `release.yml` — Build, Push & Deploy

Triggered by **manual dispatch** (`gh workflow run release`) or pushing a tag matching `v*`.
This is a single job that runs all release steps sequentially:

1. **Determine version** — CalVer from current date (+ optional patch number)
2. **Run tests + security scan** — gate before any artifacts are published
3. **Build & push Docker images** — to GHCR with tags `latest` + version
4. **Commit version bump** — updates `app/version.py` and pushes to `main`
5. **Tag & GitHub Release** — creates git tag + GitHub Release with auto-generated changelog
6. **SSH deploy** — pulls images on production server, runs compose, health check on `HEALTH_PORT` (default 5050)

Docker images carry OCI labels: `org.opencontainers.image.version`, `org.opencontainers.image.created`.

### Required GitHub Secrets

Configure these in **Settings → Secrets and variables → Actions**:

| Secret           | Description                           |
| ---------------- | ------------------------------------- |
| `DEPLOY_HOST`    | Production server hostname or IP      |
| `DEPLOY_USER`    | SSH username on the production server |
| `DEPLOY_SSH_KEY` | SSH private key for deployment        |

> `GITHUB_TOKEN` is used automatically for GHCR authentication — no extra token needed.

### GitHub Environment

Create a **production** environment in **Settings → Environments** to enable
deployment protection rules (required reviewers, wait timer, etc.).

---

## Caddy Reverse Proxy

Production deployments include Caddy (`docker-compose.prod.yml`) as the external-facing server.

### What Caddy Handles

| Feature               | Details                                                                                                                 |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| **Reverse proxy**     | Routes all traffic to `spectra-app:5000` internally                                                                     |
| **TLS termination**   | Auto-provisions Let's Encrypt certs when `SPECTRA_DOMAIN` is set to a real domain                                       |
| **Security headers**  | CSP, HSTS (63072000s, preload), X-Frame-Options DENY, X-Content-Type-Options nosniff, X-XSS-Protection, Referrer-Policy |
| **WebSocket support** | Detects `Upgrade: websocket` and proxies correctly                                                                      |
| **Health checks**     | Polls `/api/health` every 15s with 5s timeout                                                                           |
| **Timeouts**          | 300s read/write for long-running tool executions                                                                        |

### Configuration

The production Caddyfile is at `docker/Caddyfile.prod`:

```
{$SPECTRA_DOMAIN:localhost} {
    reverse_proxy spectra-app:5000 { ... }
    header { <security headers> }
}
```

Set `SPECTRA_DOMAIN` in your `.env` to your real domain for automatic TLS:

```bash
SPECTRA_DOMAIN=spectra.example.com
```

When using `localhost` (default), Caddy serves on port 443 with a self-signed cert.

### Port Reference

| Port | Context                             | Service                     |
| ---- | ----------------------------------- | --------------------------- |
| 443  | Production (default `SPECTRA_PORT`) | Caddy → app                 |
| 80   | Production                          | Caddy (HTTP→HTTPS redirect) |
| 5050 | Deploy health check (`HEALTH_PORT`) | Caddy or direct             |
| 5000 | Development / internal              | App container directly      |

---

## How Releases Work

1. **Develop** on feature branches, merge to `main` via PR.
2. CI runs lint + tests + security scan on every push/PR.
3. **To release**: run `gh workflow run release` or push a version tag:

```bash
git tag v2026.03.07
git push origin v2026.03.07
```

4. `release.yml` runs: tests → build images → push to GHCR → commit version bump → create GitHub Release → SSH deploy.
5. Deploy step pulls images, runs `docker compose up`, then polls `http://localhost:${HEALTH_PORT}/api/health` for up to 60 seconds.
6. If the health check fails, the deploy step exits with an error code. **Manual rollback is required** (see below).

---

## Manual Deployment

### 1. Prepare the Server

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Create project directory
sudo mkdir -p /opt/spectra
sudo chown $USER:$USER /opt/spectra
cd /opt/spectra
```

### 2. Get Compose File

You only need the compose file and env — no source code:

```bash
# Download or copy from the repo:
curl -fsSL https://raw.githubusercontent.com/breixopd14/spectra/main/docker/docker-compose.prod.yml \
  -o docker/docker-compose.prod.yml
curl -fsSL https://raw.githubusercontent.com/breixopd14/spectra/main/docker/Caddyfile.prod \
  -o docker/Caddyfile.prod
```

### 3. Configure Environment

Create `.env` with production values:

```bash
# .env — production secrets
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET_KEY=$(openssl rand -hex 32)

# Domain for Caddy TLS (leave as localhost for HTTP-only)
SPECTRA_DOMAIN=spectra.example.com

# AI Provider — Qwen via DashScope (recommended)
AI_PROVIDER=litellm
LLM_API_KEY=sk-your-dashscope-api-key
LLM_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3-32b

# Or OpenAI:
# AI_PROVIDER=litellm
# LLM_API_KEY=sk-...
# LLM_MODEL=gpt-4o-mini

FULLY_AUTOMATED=false
PLUGIN_SAFE_MODE=true
```

### 4. Deploy

```bash
docker compose -f docker/docker-compose.prod.yml pull  # or 'build' if not using GHCR
docker compose -f docker/docker-compose.prod.yml up -d
```

### 5. Setup

Open `https://<your-domain>` → create admin account → configure AI provider → done.

### 6. Verify

```bash
curl -f https://spectra.example.com/api/health
docker compose -f docker/docker-compose.prod.yml ps
docker compose -f docker/docker-compose.prod.yml logs --tail=50
```

---

## Rollback Procedures

### Manual Rollback

The CI deploy does **not** automatically roll back on health check failure.
When a deploy fails, roll back manually:

```bash
cd /opt/spectra

# Roll back to a specific version
export VERSION=2026.03.06
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d

# Verify
curl -f https://spectra.example.com/api/health
```

### Database Rollback

If a migration caused the issue:

```bash
docker compose -f docker/docker-compose.prod.yml exec app alembic downgrade -1
```

---

## Maintenance

### Database Backups

```bash
docker compose -f docker/docker-compose.prod.yml exec db \
  pg_dump -U spectra spectra > backup_$(date +%F).sql
```

### Viewing Logs

```bash
docker compose -f docker/docker-compose.prod.yml logs -f app
docker compose -f docker/docker-compose.prod.yml logs -f tools
docker compose -f docker/docker-compose.prod.yml logs -f caddy
```

### Updating Plugins

Place new signed `.json` files in the `plugins/` directory on the server
and restart the tools container:

```bash
docker compose -f docker/docker-compose.prod.yml restart tools
```

---

## Environment Variables Reference

### Required

| Variable            | Description                      |
| ------------------- | -------------------------------- |
| `POSTGRES_PASSWORD` | PostgreSQL password              |
| `JWT_SECRET_KEY`    | Secret key for JWT token signing |
| `DATABASE_URL`      | Set automatically by compose     |

### Application

| Variable           | Default | Description                         |
| ------------------ | ------- | ----------------------------------- |
| `AI_PROVIDER`      | `api`   | LLM backend: `api`, `local`, `mock` |
| `LLM_API_KEY`      | —       | API key for external LLM            |
| `FULLY_AUTOMATED`  | `false` | Skip human approval gates           |
| `PLUGIN_SAFE_MODE` | `true`  | Require signed plugins              |
| `DEBUG`            | `false` | Enable debug mode                   |

### Infrastructure

| Variable              | Default         | Description                      |
| --------------------- | --------------- | -------------------------------- |
| `TOOL_CONTAINER_NAME` | `spectra-tools` | Name of the tools container      |
| `CONNECT_BACK_HOST`   | `spectra-app`   | Hostname tools use to reach app  |
| `IS_TOOLS_CONTAINER`  | `false`         | Set `true` in tools container    |
| `SPECTRA_DOMAIN`      | `localhost`     | Domain for Caddy TLS             |
| `SPECTRA_PORT`        | `443`           | External port for Caddy (prod)   |
| `HEALTH_PORT`         | `5050`          | Port used by deploy health check |

---

## Troubleshooting

### Health check fails after deploy

```bash
# Check app logs
docker compose -f docker/docker-compose.prod.yml logs app --tail=100

# Check Caddy logs
docker compose -f docker/docker-compose.prod.yml logs caddy --tail=100

# Check DB is reachable
docker compose -f docker/docker-compose.prod.yml exec app nc -z db 5432
```

### Database migration failed

```bash
# Check migration status
docker compose -f docker/docker-compose.prod.yml exec app alembic current

# Manual upgrade
docker compose -f docker/docker-compose.prod.yml exec app alembic upgrade head
```

### Caddy TLS issues

```bash
# Check Caddy logs for certificate errors
docker compose -f docker/docker-compose.prod.yml logs caddy

# Test with HTTP (bypass TLS for debugging)
curl -f http://localhost:80/api/health
```

Ensure your domain's DNS A record points to the server. Caddy auto-provisions
TLS via Let's Encrypt when a real domain is configured in `SPECTRA_DOMAIN`.
