# Deployment

[← Wiki Home](home.md) | [Deployment Guide](deployment-guide.md) | [Configuration](configuration.md) | [Scaling](scaling.md)

---

> **See [Deployment Guide](deployment-guide.md) for the complete production deployment guide** — Docker Compose, Cloudflare, Docker Swarm, Portainer, scaling, backups, and monitoring.

This page covers CI/CD pipeline configuration and versioning.

Current runtime contract: Docker Compose and Docker Swarm use the same internal service names and ports for the microservices split (`ai-svc:5010`, `scheduler:5011`, `worker:5012`). S3-compatible storage is required for missions, sessions, knowledge, and backups; use bundled MinIO or point to an external S3 endpoint.

## Services

| Service | Image | Purpose |
|---------|-------|---------|
| **db** | `pgvector/pgvector:pg16` | PostgreSQL + pgvector (persistent state, PostgreSQL-backed app cache, job queue, LISTEN/NOTIFY backbone, RAG) |
| **redis** | `redis:7-alpine` | Shared distributed rate-limiting backend |
| **caddy** | `caddy:2-alpine` | Reverse proxy — TLS, security headers, WebSocket |
| **app** | `ghcr.io/breixopd14/spectra-app` | FastAPI backend (internal port 5000) |
| **ai-svc** | `ghcr.io/breixopd14/spectra-ai-svc` | AI/LLM service (internal port 5010) |
| **scheduler** | `ghcr.io/breixopd14/spectra-scheduler` | Background tasks (internal port 5011) |
| **worker** | `ghcr.io/breixopd14/spectra-worker` | Tool execution (internal port 5012) |
| **minio** | `minio/minio` | Self-hosted S3-compatible object storage (required unless external S3 is configured) |

All inter-service communication uses PostgreSQL as the persistent state store, PostgreSQL-backed app cache, job queue, and `NOTIFY`/`LISTEN` backbone, plus HTTP with `SERVICE_AUTH_SECRET`. Redis is the shared distributed rate-limiting backend.

`RATE_LIMIT_STORAGE=memory://` is acceptable for tests or intentionally ephemeral local runs, but it is not the normal deployment recommendation. Keep Redis as the shared distributed rate-limiting backend for deployments. Use Caddy rate limiting only if you intentionally want rate limiting to live entirely at the edge.

Swarm supports `_FILE` secret environment variables such as `POSTGRES_PASSWORD_FILE`, `SERVICE_AUTH_SECRET_FILE`, and `JWT_SECRET_KEY_FILE` while keeping the same internal hostnames and ports as Compose.

> **Tip:** Set `REGISTRY` and `VERSION` environment variables to control image sources.
> Local dev uses `spectra-app:latest` by default; production can set
> `REGISTRY=ghcr.io/breixopd14/` and `VERSION=2026.03.13` to pull release images.

## Versioning

Spectra uses **CalVer** (date-based versioning): `YYYY.MM.DD[.patch]`

```bash
python version.py                # 2026.03.13
python version.py --patch 1      # 2026.03.13.1
```

---

## Quick Start (Development)

```bash
git clone <repo-url> && cd spectra
cp .env.example .env
# Edit .env — at minimum set JWT_SECRET_KEY

# Monolith mode:
cd docker && docker compose up -d

# Microservices mode:
cd docker && docker compose up -d
```

- **Dev UI:** `http://localhost:5000`
- Create your admin account at `/setup`
- Configure your AI provider through the web UI

---

## CI/CD Pipeline

### `ci.yml` — Continuous Integration

Triggered on every push/PR to `main` or `develop`.

| Job | Purpose |
|-----|---------|
| **lint** | `ruff check` on app code |
| **test** | Containerized validation (`docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner`) |
| **security** | Bandit security scan (HIGH severity gate) |
| **docker-build** | Builds runtime images and validates both Compose and Swarm config with `.env.example` |
| **deps** | Dependency audit |

### `release.yml` — Build, Push & Deploy

Triggered by **manual dispatch** or pushing a tag matching `v*`.

1. Determine version (CalVer from current date)
2. Run tests + security scan
3. Build & push Docker images to GHCR with `latest` + version tags
4. Commit version bump to `main`
5. Create git tag + GitHub Release with auto-generated changelog
6. SSH deploy with health check

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Production server hostname or IP |
| `DEPLOY_USER` | SSH username |
| `DEPLOY_SSH_KEY` | SSH private key for deployment |

---

## Rollback

### Manual Rollback

```bash
cd /opt/spectra
export VERSION=2026.03.06
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up -d
curl -f https://spectra.example.com/api/health
```

### Database Rollback

```bash
docker compose exec app alembic downgrade -1
```
