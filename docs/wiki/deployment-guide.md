# Deployment Guide

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Scaling](scaling.md) | [Security](security.md)

---

Complete guide for deploying Spectra in production with Docker Compose, TLS, and operational best practices.

## Prerequisites

- Docker Engine 24.0+ and Docker Compose v2.20+
- A server with at least 4 CPU cores, 8 GB RAM, 50 GB disk
- A domain name pointed at the server (for automatic TLS via Let's Encrypt)

---

## Docker Compose Production Setup

### 1. Prepare the Server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo mkdir -p /opt/spectra && sudo chown $USER:$USER /opt/spectra
cd /opt/spectra
```

### 2. Get Compose Files

```bash
curl -fsSL https://raw.githubusercontent.com/breixopd14/spectra/main/docker/docker-compose.prod.yml \
  -o docker/docker-compose.prod.yml
curl -fsSL https://raw.githubusercontent.com/breixopd14/spectra/main/docker/Caddyfile.prod \
  -o docker/Caddyfile.prod
```

### 3. Configure Environment

```bash
cat > .env <<'EOF'
# --- REQUIRED ---
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET_KEY=$(openssl rand -hex 32)
SPECTRA_DOMAIN=spectra.example.com

# --- AI Provider ---
AI_PROVIDER=litellm
LLM_API_KEY=sk-your-api-key
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# --- Security ---
FULLY_AUTOMATED=false
PLUGIN_SAFE_MODE=true

# --- Storage (optional, for MinIO) ---
MINIO_ROOT_PASSWORD=$(openssl rand -hex 16)
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=spectra
S3_SECRET_KEY=$(openssl rand -hex 16)
EOF
```

### Required Environment Variables

| Variable | Why Required | Notes |
|----------|-------------|-------|
| `POSTGRES_PASSWORD` | Database authentication | Must match between `db` and `app` services |
| `JWT_SECRET_KEY` | Token signing | If unset, sessions invalidate on every restart |
| `SPECTRA_DOMAIN` | TLS certificate provisioning | Set to your real domain for Let's Encrypt |

### 4. Deploy

```bash
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d
```

### 5. Verify

```bash
curl -f https://spectra.example.com/api/health
docker compose -f docker/docker-compose.prod.yml ps
docker compose -f docker/docker-compose.prod.yml logs --tail=50
```

### 6. Initial Setup

Navigate to `https://spectra.example.com/setup` to create the admin account. This endpoint is only available once (when no users exist).

---

## FULLY_AUTOMATED Production Warning

> **Never set `FULLY_AUTOMATED=true` in production.** This mode bypasses all human approval gates — missions execute without operator confirmation. Use only in isolated lab/testing environments.

In production, always set:

```env
FULLY_AUTOMATED=false
REQUIRE_APPROVAL=true   # Optional: require explicit approval for high-risk actions
```

---

## SSL/TLS with Caddy

Production deployments use Caddy as a reverse proxy with automatic TLS.

### What Caddy Provides

| Feature | Details |
|---------|---------|
| **TLS termination** | Auto-provisioned Let's Encrypt certificates |
| **Security headers** | CSP, HSTS (63072000s, preload), X-Frame-Options DENY |
| **WebSocket proxy** | Automatic upgrade detection and proxying |
| **Health checks** | Polls `/api/health` every 15s |
| **Timeouts** | 300s read/write for long-running operations |

### Port Layout

| Port | Context | Service |
|------|---------|---------|
| 443 | Production (default) | Caddy → app |
| 80 | Production | HTTP → HTTPS redirect |
| 5000 | Internal only | App container (not exposed) |

### Configuration

Set `SPECTRA_DOMAIN` in `.env`:

```bash
SPECTRA_DOMAIN=spectra.example.com
```

When using `localhost`, Caddy serves on port 443 with a self-signed certificate.

---

## Scaling Considerations

### Single-Instance Constraints

Several subsystems use in-memory state and do not support horizontal scaling without modification:

| Subsystem | State | Impact |
|-----------|-------|--------|
| **WebSocket connections** | In-memory connection set | Clients only receive events from their app instance |
| **Rate limiter** | In-memory counters | Per-process limits, not global |
| **Mission state** | In-memory `active_missions` dict | A mission must stay on the instance that started it |
| **Blackboard** | In-memory LRU cache | Agent context not shared across instances |
| **Account lockout** | File-based + in-memory | Lockout state per instance |

### Scaling Strategies

- **Vertical scaling** (recommended first): Increase CPU/RAM on the single host
- **Database**: PostgreSQL handles connection pooling natively; consider read replicas for heavy query loads
- **Storage**: Use S3/MinIO for mission data to decouple from local filesystem
- **Workers**: Deploy additional tools containers for parallel tool execution (see [Scaling](scaling.md))
- **Rate limiting**: Switch to Redis-backed storage for shared rate limit state
- **WebSocket**: Use a message bus (Redis pub/sub) to broadcast events across instances

---

## Backup Strategy

### PostgreSQL

```bash
# Full database dump
docker compose -f docker/docker-compose.prod.yml exec db \
  pg_dump -U spectra spectra > backup_$(date +%F).sql

# Restore from backup
cat backup_2026-03-11.sql | docker compose -f docker/docker-compose.prod.yml exec -T db \
  psql -U spectra spectra
```

Schedule daily automated backups:

```bash
# crontab -e
0 2 * * * cd /opt/spectra && docker compose -f docker/docker-compose.prod.yml exec -T db \
  pg_dump -U spectra spectra | gzip > /opt/backups/spectra_$(date +\%F).sql.gz
```

### File Storage

If using local filesystem storage:

```bash
# Back up mission data, reports, and auth state
tar czf spectra-data_$(date +%F).tar.gz data/ reports/ keys/
```

If using S3/MinIO:

```bash
# MinIO volume is persisted in Docker volume `minio_data`
docker run --rm -v spectra_minio_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/minio_$(date +%F).tar.gz /data
```

### What to Back Up

| Data | Location | Frequency |
|------|----------|-----------|
| Database | PostgreSQL container | Daily |
| Mission data | `data/missions/` or S3 | Daily |
| Auth state | `data/auth/` | Daily |
| Plugin signing keys | `keys/` | On change |
| Configuration | `.env` | On change |
| TLS certificates | Caddy volume `caddy_data` | Weekly |

---

## Maintenance

### Database Migrations

Migrations run automatically on app startup via `scripts/start.sh`. For manual control:

```bash
# Check current migration
docker compose -f docker/docker-compose.prod.yml exec app alembic current

# Apply pending migrations
docker compose -f docker/docker-compose.prod.yml exec app alembic upgrade head

# Rollback one migration
docker compose -f docker/docker-compose.prod.yml exec app alembic downgrade -1
```

### Viewing Logs

```bash
docker compose -f docker/docker-compose.prod.yml logs -f app
docker compose -f docker/docker-compose.prod.yml logs -f tools
docker compose -f docker/docker-compose.prod.yml logs -f caddy
```

### Updating

```bash
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 80/443 in use | Change port mapping in Caddy service or stop conflicting service |
| Database connection fails | Verify `POSTGRES_PASSWORD` matches between `.env` and compose |
| Migrations fail | Check `docker logs spectra-app` for migration errors |
| Setup page not loading | Ensure all services are healthy: `docker compose ps` |
| PDF export fails | Install `libcairo2-dev`, `pkg-config`, `python3-dev` in the app image |
| Caddy TLS errors | Ensure `SPECTRA_DOMAIN` is set and DNS points to this server |
| WebSocket disconnects | Check Caddy logs for proxy errors; verify firewall allows upgrades |
