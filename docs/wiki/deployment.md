# Deployment

[← Wiki Home](home.md) | [Deployment Guide](deployment-guide.md) | [Configuration](configuration.md) | [Scaling](scaling.md)

---

> **See [Deployment Guide](deployment-guide.md) for the complete production deployment guide** — Docker Compose, Cloudflare, Docker Swarm, Portainer, scaling, backups, and monitoring.

This page covers CI/CD pipeline configuration and versioning.

## Services

| Service | Image | Purpose |
|---------|-------|---------|
| **db** | `pgvector/pgvector:pg16` | PostgreSQL + pgvector (data, cache, queues, RAG) |
| **caddy** | `caddy:2-alpine` | Reverse proxy — TLS, security headers, WebSocket |
| **app** | `ghcr.io/breixopd14/spectra-app` | FastAPI backend (internal port 5000) |
| **ai-svc** | `ghcr.io/breixopd14/spectra-app` | AI/LLM service (internal port 5010) |
| **scheduler** | `ghcr.io/breixopd14/spectra-app` | Background tasks (internal port 5011) |
| **worker** | `ghcr.io/breixopd14/spectra-app` | Tool execution (internal port 5012) |
| **minio** | `minio/minio` | S3-compatible object storage (optional) |

All inter-service communication uses PostgreSQL (job queue, pub/sub via NOTIFY/LISTEN) and HTTP with `SERVICE_AUTH_SECRET`. No Redis or external message broker.

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
cd docker && docker compose -f docker-compose.yml -f docker-compose.services.yml up -d
```

- **Dev UI:** http://localhost:5000
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
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d
curl -f https://spectra.example.com/api/health
```

### Database Rollback

```bash
docker compose exec app alembic downgrade -1
```
