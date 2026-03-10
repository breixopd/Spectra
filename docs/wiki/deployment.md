# Deployment

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Scaling](scaling.md) | [Architecture](architecture.md)

---

Spectra uses Docker Compose for deployment with a CI/CD pipeline via GitHub Actions. Images are pushed to GitHub Container Registry (GHCR) and deployed automatically on release.

## Services

| Service | Image | Purpose |
|---------|-------|---------|
| **db** | `pgvector/pgvector:pg16` | PostgreSQL + pgvector (data, cache, queues, RAG) |
| **caddy** | `caddy:2-alpine` | Reverse proxy — TLS, security headers, rate limiting |
| **app** | `ghcr.io/breixopd14/spectra-app` | FastAPI backend (internal port 5000) |
| **tools** | `ghcr.io/breixopd14/spectra-tools` | Kali Linux security worker |
| **minio** | `minio/minio` | S3-compatible object storage (optional) |

In production, Caddy sits in front of the app. External traffic hits Caddy (port 443 by default); Caddy proxies to the app container on port 5000 internally.

## Prerequisites

- Docker Engine 24.0+ and Docker Compose v2.20+
- A server with at least 4 CPU cores, 8 GB RAM, 50 GB disk
- A domain name pointed at the server (for automatic TLS via Let's Encrypt)

## Versioning

Spectra uses **CalVer** (date-based versioning): `YYYY.MM.DD[.patch]`

```bash
python version.py                # 2026.03.07
python version.py --patch 1      # 2026.03.07.1
```

---

## Quick Start (Development)

```bash
git clone <repo-url> && cd spectra
cp .env.example .env
# Edit .env — at minimum set JWT_SECRET_KEY

cd docker
docker compose up -d
```

- **Dev UI:** http://localhost:5000
- Create your admin account at `/setup`
- Configure your AI provider through the web UI

---

## Production Deployment

### 1. Prepare the Server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo mkdir -p /opt/spectra && sudo chown $USER:$USER /opt/spectra
cd /opt/spectra
```

### 2. Get Compose File

```bash
curl -fsSL https://raw.githubusercontent.com/breixopd14/spectra/main/docker/docker-compose.prod.yml \
  -o docker/docker-compose.prod.yml
curl -fsSL https://raw.githubusercontent.com/breixopd14/spectra/main/docker/Caddyfile.prod \
  -o docker/Caddyfile.prod
```

### 3. Configure Environment

```bash
cat > .env <<'EOF'
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET_KEY=$(openssl rand -hex 32)
SPECTRA_DOMAIN=spectra.example.com

AI_PROVIDER=litellm
LLM_API_KEY=sk-your-api-key
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

FULLY_AUTOMATED=false
PLUGIN_SAFE_MODE=true
EOF
```

See [Configuration](configuration.md) for all available settings.

### 4. MinIO/S3 Storage (Optional)

Add MinIO to your Compose file or configure cloud S3:

```bash
# In .env for local MinIO
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=spectra-admin
S3_SECRET_KEY=spectra-secret-key

# Or for AWS S3
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
S3_REGION=us-east-1
```

See [Scaling](scaling.md) for full S3/MinIO setup and migration.

### 5. Deploy

```bash
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d
```

### 6. Verify

```bash
curl -f https://spectra.example.com/api/health
docker compose -f docker/docker-compose.prod.yml ps
docker compose -f docker/docker-compose.prod.yml logs --tail=50
```

---

## Caddy Reverse Proxy

Production deployments include Caddy (`docker-compose.prod.yml`) as the external-facing server.

### What Caddy Handles

| Feature | Details |
|---------|---------|
| **Reverse proxy** | Routes all traffic to `spectra-app:5000` internally |
| **TLS termination** | Auto-provisions Let's Encrypt certs when `SPECTRA_DOMAIN` is set |
| **Security headers** | CSP, HSTS (63072000s, preload), X-Frame-Options DENY, X-Content-Type-Options nosniff |
| **WebSocket support** | Detects `Upgrade: websocket` and proxies correctly |
| **Health checks** | Polls `/api/health` every 15s with 5s timeout |
| **Timeouts** | 300s read/write for long-running tool executions |

### Configuration

Set `SPECTRA_DOMAIN` in `.env` to your real domain for automatic TLS:

```bash
SPECTRA_DOMAIN=spectra.example.com
```

When using `localhost` (default), Caddy serves on port 443 with a self-signed cert.

### Port Reference

| Port | Context | Service |
|------|---------|---------|
| 443 | Production (default) | Caddy → app |
| 80 | Production | Caddy (HTTP→HTTPS redirect) |
| 5050 | Deploy health check | Caddy or direct |
| 5000 | Development / internal | App container directly |

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

Place new signed `.json` files in the `plugins/` directory and restart:

```bash
docker compose -f docker/docker-compose.prod.yml restart tools
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 80 already in use | Change port mapping in Caddy service |
| Database connection fails | Check `POSTGRES_PASSWORD` matches in `.env` and compose file |
| "Container unhealthy" | Wait 30s for DB init, then check `docker logs spectra-app` |
| Migrations fail | Ensure `DATABASE_URL` matches your `POSTGRES_PASSWORD` |
| Setup page not loading | Check `docker logs spectra-app` for startup errors |
| PDF export not working | `xhtml2pdf` is optional — requires `libcairo2-dev`, `pkg-config`, `python3-dev` |
| Caddy not starting | Ensure ports 443/80 are free; check `docker logs spectra-caddy` |
| Caddy TLS errors | Set `SPECTRA_DOMAIN` to your real domain; Caddy auto-provisions Let's Encrypt |
| RAG search returns no results | Configure an embedding-capable LLM API via the Settings page |

For multi-server deployment, see the [Scaling Guide](scaling.md).
