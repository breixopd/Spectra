# Deployment Guide

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Scaling](scaling.md) | [Security](security.md)

---

Complete guide for deploying Spectra in production — from single-server Docker Compose to multi-host Docker Swarm with Cloudflare and Caddy.

## Prerequisites

- Linux server(s) with Docker Engine 24.0+ and Docker Compose v2.20+
- At least 4 CPU cores, 8 GB RAM, 50 GB disk
- Domain name (optional but recommended)
- Cloudflare account (free tier, recommended)

## Architecture

Spectra runs as microservices, all deployed via Docker:

| Service | Container | Port | Purpose | Replicas |
|---------|-----------|------|---------|----------|
| **app** | `spectra-app` | 5000 | Web UI + REST API | 1–3 |
| **ai-service** | `spectra-ai-svc` | 5010 | LLM routing, embeddings, RAG | 1 |
| **scheduler** | `spectra-scheduler` | 5011 | Background jobs, backups, metrics, sandbox watchdog | 1 |
| **worker** | `spectra-worker` | 5012 | Tool execution (manages ephemeral sandbox containers) | 1–3 |
| **db** | `spectra-db` | 5432 | PostgreSQL + pgvector (data, cache, job queue, pub/sub) | 1 |
| **caddy** | `spectra-caddy` | 80/443 | Reverse proxy — TLS, security headers | 1 |
| **minio** | `spectra-minio` | 9000 | S3-compatible object storage (optional) | 1 |

### Inter-Service Communication

All services communicate using:

- **PostgreSQL** for persistent state, job queue (`SELECT ... FOR UPDATE SKIP LOCKED`), and pub/sub (`NOTIFY`/`LISTEN`)
- **HTTP + shared secret** (`X-Service-Auth` header) for direct service-to-service API calls
- **No Redis, no external message broker** — PostgreSQL handles everything

### Sandbox Containers

Each mission gets one ephemeral sandbox container (Kali Linux) for tool execution. The worker service manages these containers via Docker socket. Sandboxes are auto-cleaned after mission completion — no need for additional tools containers.

---

## Quick Start (Single Server)

### 1. Prepare the Server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo mkdir -p /opt/spectra && sudo chown $USER:$USER /opt/spectra
cd /opt/spectra
git clone <repo-url> .
```

### 2. Configure Environment

```bash
cat > .env <<'EOF'
# --- Required ---
POSTGRES_PASSWORD=<generate with: openssl rand -hex 16>
JWT_SECRET_KEY=<generate with: openssl rand -hex 32>
SERVICE_AUTH_SECRET=<generate with: openssl rand -hex 32>

# --- Domain (for Caddy TLS) ---
SPECTRA_DOMAIN=spectra.example.com

# --- AI Provider ---
AI_PROVIDER=litellm
LLM_API_KEY=sk-your-api-key
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# --- Security ---
FULLY_AUTOMATED=false
PLUGIN_SAFE_MODE=true

# --- S3/MinIO (optional) ---
# MINIO_ROOT_USER=spectra
# MINIO_ROOT_PASSWORD=<generate with: openssl rand -hex 16>
# S3_ENDPOINT_URL=http://minio:9000
# S3_ACCESS_KEY=spectra
# S3_SECRET_KEY=<same as MINIO_ROOT_PASSWORD>
EOF
```

See [Configuration](configuration.md) for all available settings.

### 3. Deploy (All Services)

```bash
# All services (microservices mode by default)
docker compose -f docker/docker-compose.yml up -d
```

This starts all services as separate containers with health checks:
- `spectra-app` — Core API + Web UI
- `spectra-ai-svc` — AI/LLM service
- `spectra-scheduler` — Background tasks
- `spectra-worker` — Tool execution
- `spectra-db` — PostgreSQL
- `spectra-caddy` — Reverse proxy

### 4. Setup Wizard

Open `http://your-server:5000` (or `https://spectra.example.com` if Caddy + domain configured).
First visit redirects to `/setup` → create the admin account.

### 5. Verify

```bash
# Check all containers are healthy
docker compose -f docker/docker-compose.yml ps

# Health check
curl -f http://localhost:5000/api/health

# Tail logs
docker compose -f docker/docker-compose.yml logs -f app
```

---

## Cloudflare Setup (Free Tier)

Cloudflare provides DDoS protection, a WAF, global CDN for static assets, SSL, and analytics — all on the free tier.

### 1. Add Your Site

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → **Add Site** → enter your domain
2. Select **Free** plan
3. Cloudflare scans existing DNS records

### 2. Update Nameservers

Set your domain's NS records to the Cloudflare nameservers shown in the dashboard. This varies by registrar — update via your registrar's DNS settings panel.

### 3. DNS Records

In Cloudflare DNS settings, create:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `spectra` | `<your-server-IP>` | **Proxied** (orange cloud) |

The orange cloud means traffic routes through Cloudflare's network (DDoS protection, CDN, WAF).

### 4. SSL/TLS Mode

Go to **SSL/TLS** → **Overview**:

| Mode | When to Use |
|------|-------------|
| **Full (Strict)** | Recommended. Caddy auto-provisions a valid Let's Encrypt cert on your origin. Cloudflare verifies it. |
| **Full** | If Caddy generates a self-signed cert. Cloudflare encrypts origin traffic but doesn't verify the cert. |
| **Flexible** | Not recommended — origin traffic is unencrypted. Only use if you cannot run HTTPS on origin. |

### 5. Security Rules (Free)

- **WAF → Managed Rules**: Enable the free managed ruleset (basic protection against common attacks)
- **Security → Settings → Bot Fight Mode**: Enable to challenge automated threats
- **Under Attack Mode**: Available on-demand for active DDoS attacks (adds a JS challenge page)

### 6. Caching Rules

Go to **Caching → Cache Rules** (or **Rules → Page Rules** on older plans):

| Rule | Match | Action |
|------|-------|--------|
| API bypass | `spectra.example.com/api/*` | **Bypass Cache** |
| Static cache | `spectra.example.com/static/*` | **Cache Everything**, Edge TTL: 1 month |
| WebSocket bypass | `spectra.example.com/ws/*` | **Bypass Cache** |

### 7. Caddy Origin Config

With Cloudflare in **Full (Strict)** mode, Caddy handles origin TLS:

```caddyfile
# docker/Caddyfile.prod
spectra.yourdomain.com {
    reverse_proxy spectra-app:5000 {
        health_uri /api/health
        health_interval 15s
        health_timeout 5s
        transport http {
            read_timeout 300s
            write_timeout 300s
        }
    }

    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        -Server
    }
}
```

Caddy automatically provisions a Let's Encrypt certificate. Cloudflare proxies to it over HTTPS.

### What You Get (Free Tier)

| Feature | Details |
|---------|---------|
| DDoS protection | Automatic L3/L4/L7 mitigation |
| WAF | Basic managed rules, bot fight mode |
| CDN | Static assets cached at 300+ edge locations |
| SSL | End-to-end encryption (Cloudflare ↔ origin) |
| Analytics | Request volume, bandwidth, threat metrics |
| Always Online | Serves cached pages if origin is down |

---

## Production: Docker Compose

The main Compose file (`docker/docker-compose.yml`) is pre-configured with:
- Resource limits on all containers
- MinIO for S3 storage (internal only, no exposed ports)
- Caddy reverse proxy
- All volumes persisted

For production, create a `.env.prod` with required secrets and use:

```bash
docker compose -f docker/docker-compose.yml --env-file .env.prod up -d
```

### Required Environment Variables

| Variable | Why Required |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database authentication |
| `JWT_SECRET_KEY` | Token signing — sessions invalidate on restart if unset |
| `SERVICE_AUTH_SECRET` | Inter-service authentication (microservices mode) |
| `SPECTRA_DOMAIN` | TLS certificate provisioning via Let's Encrypt |
| `MINIO_ROOT_PASSWORD` | S3 storage authentication (if MinIO is used) |

### SSL/TLS with Caddy

| Feature | Details |
|---------|---------|
| **TLS termination** | Auto-provisioned Let's Encrypt certificates |
| **Security headers** | CSP, HSTS (63072000s, preload), X-Frame-Options DENY |
| **WebSocket proxy** | Automatic upgrade detection and proxying |
| **Health checks** | Polls `/api/health` every 15s |
| **Timeouts** | 300s read/write for long-running operations |

Set `SPECTRA_DOMAIN` in `.env`:

```bash
SPECTRA_DOMAIN=spectra.example.com
```

When using `localhost`, Caddy serves on port 443 with a self-signed certificate.

---

## Production: Docker Swarm (Multi-Server)

Docker Swarm is built into Docker Engine — no extra software to install. Use it when you need multiple hosts, rolling updates, or secret management.

A pre-built Swarm stack is at `docker/docker-compose.swarm.yml`.

### 1. Initialize Swarm

```bash
# On the manager node:
docker swarm init --advertise-addr <MANAGER_IP>

# Save the join token from the output, then on each worker node:
docker swarm join --token <TOKEN> <MANAGER_IP>:2377
```

### 2. Label Nodes

Assign roles so services land on the right hardware:

```bash
docker node update --label-add role=app <APP_NODE_HOSTNAME>
docker node update --label-add role=db <DB_NODE_HOSTNAME>
docker node update --label-add role=worker <WORKER_NODE_HOSTNAME>
docker node update --label-add role=ai <GPU_NODE_HOSTNAME>    # Optional: GPU node for local LLM
```

### 3. Create Secrets

Swarm secrets are encrypted at rest and only available to services that reference them:

```bash
echo "$(openssl rand -hex 16)" | docker secret create db_password -
echo "$(openssl rand -hex 32)" | docker secret create service_auth -
echo "$(openssl rand -hex 32)" | docker secret create jwt_secret -
```

### 4. Create Configs

```bash
docker config create caddyfile docker/Caddyfile.prod
```

### 5. Deploy the Stack

```bash
docker stack deploy -c docker/docker-compose.swarm.yml spectra
```

### 6. Verify

```bash
# List all services and their replica status
docker service ls

# Check a specific service
docker service ps spectra_app

# Follow logs
docker service logs spectra_app --follow

# Health check
curl -f http://<MANAGER_IP>:5000/api/health
```

### Swarm Service Layout

The `docker-compose.swarm.yml` defines these services with placement constraints:

| Service | Placement | Replicas | Secrets |
|---------|-----------|----------|---------|
| `db` | `node.labels.role == db` | 1 | `db_password` |
| `app` | `node.labels.role == app` | 2 | `db_password`, `service_auth`, `jwt_secret` |
| `ai-service` | `node.labels.role == ai` | 1 | `service_auth` |
| `scheduler` | `node.labels.role == app` | 1 | `service_auth` |
| `worker` | `node.labels.role == worker` | 2 | `service_auth` |
| `caddy` | `node.labels.role == app` | 1 | — (uses config) |

The overlay network (`spectra-net`) spans all Swarm nodes automatically.

### Rolling Updates

Swarm performs zero-downtime updates by default:

```bash
# Update the app image across all replicas
docker service update --image spectra-app:v2 spectra_app

# The swarm.yml configures: parallelism=1, delay=10s, order=start-first
# So one replica updates while the other continues serving traffic.
```

---

## Portainer (Optional Management UI)

Portainer Community Edition is a free web UI for managing Docker containers, images, volumes, and networks across one or many hosts.

### Install Portainer (Manager Node)

```bash
docker volume create portainer_data

docker run -d -p 9443:9443 --name portainer --restart always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest
```

Open `https://your-server:9443` and create the admin account.

### Add Remote Docker Hosts

On each additional server, run the Portainer Agent:

```bash
docker run -d --name portainer-agent --restart always \
  -p 9001:9001 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/docker/volumes:/var/lib/docker/volumes \
  portainer/agent:latest
```

In the Portainer UI: **Environments → Add environment → Docker (Agent)** → enter `<remote-ip>:9001`.

### Deploy Spectra as a Portainer Stack

1. In Portainer, go to **Stacks → Add stack**
2. Paste the contents of `docker/docker-compose.yml` (or the swarm file for multi-host)
3. Under **Environment variables**, add `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `SERVICE_AUTH_SECRET`, `SPECTRA_DOMAIN`, etc.
4. Click **Deploy the stack**

Portainer provides:

| Feature | Details |
|---------|---------|
| **Container management** | Start/stop/restart/remove from the UI |
| **Logs** | Stream container logs in-browser |
| **Resource usage** | CPU and memory per container, real-time |
| **Stack updates** | Edit compose YAML and redeploy in one click |
| **Image management** | Pull, tag, and push images from the UI |
| **Multi-host** | Manage all Docker hosts from a single dashboard |

---

## Scaling

### App Replicas

```bash
# Docker Compose:
docker compose up -d --scale app=3

# Docker Swarm:
docker service scale spectra_app=3
```

Rate limiting and WebSocket events are coordinated via PostgreSQL — no external state store needed. Each app instance uses the shared database for rate limit state.

### Worker Replicas

```bash
# Docker Swarm:
docker service scale spectra_worker=4
```

Each worker pulls jobs from the PostgreSQL queue using `SELECT ... FOR UPDATE SKIP LOCKED` — no coordination needed. Multiple workers can process jobs in parallel without conflicts.

### Database Read Replicas

For read-heavy deployments, add PostgreSQL streaming replicas:

```bash
# On the replica node, create a base backup from the primary:
pg_basebackup -h <PRIMARY_HOST> -U replicator -D /var/lib/postgresql/data -Fp -Xs -R
```

Configure the app to use read replicas:

```bash
# In .env:
DATABASE_REPLICA_URL=postgresql+asyncpg://spectra:pass@replica-host:5432/spectra
```

Or register replicas via the admin API:

```bash
curl -X POST /api/admin/servers \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "service_type": "db",
    "name": "db-replica-1",
    "url": "postgresql+asyncpg://spectra:pass@replica-host:5432/spectra",
    "is_primary": false,
    "weight": 1
  }'
```

For managed databases with built-in replication (AWS RDS, Supabase, Neon), point `DATABASE_URL` at the managed instance:

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/spectra?sslmode=require
```

---

## Backups

### Built-in Automated Backups

The scheduler service handles automated backups:

```bash
# Enable in .env:
BACKUP_ENABLED=true
BACKUP_SCHEDULE_HOURS=24
BACKUP_RETENTION_COUNT=10
BACKUP_S3_BUCKET=spectra-backups    # Optional: upload to S3/MinIO
```

### Manual Backup via Admin API

```bash
# Trigger a backup
curl -X POST http://localhost:5000/api/admin/backups \
  -H "Authorization: Bearer <TOKEN>"

# Restore from a backup
curl -X POST http://localhost:5000/api/admin/backups/restore \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"backup_path": "/app/data/backups/backup_20260313_120000.dump"}'
```

### Manual PostgreSQL Backup

```bash
# Full database dump
docker compose exec db pg_dump -U spectra spectra > backup_$(date +%F).sql

# Restore
cat backup.sql | docker compose exec -T db psql -U spectra spectra
```

### What to Back Up

| Data | Location | Frequency |
|------|----------|-----------|
| Database | PostgreSQL container | Daily (automated via scheduler) |
| Mission data | `data/missions/` or S3 | Daily |
| Auth state | `data/auth/` | Daily |
| Plugin signing keys | `keys/` | On change |
| Configuration | `.env` | On change |
| TLS certificates | Caddy volume `caddy_data` | Weekly |

---

## Storage

Mission data storage is configurable:

| Method | Config | Best For |
|--------|--------|----------|
| **Local** (default) | `data/missions/` directory | Single-server deployments |
| **S3/MinIO** | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Multi-server, durability |

S3/MinIO support is **built-in** — set the environment variables and it works. Compatible with any S3 provider: AWS S3, Cloudflare R2, DigitalOcean Spaces, MinIO, etc.

For multi-server deployments, use S3/MinIO so all nodes access the same data:

```bash
# Self-hosted MinIO (included in docker-compose.yml):
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=spectra
S3_SECRET_KEY=your-minio-password

# Cloud S3:
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
S3_REGION=us-east-1
```

---

## Monitoring

### Health Endpoints

All services expose health endpoints:

| Service | Endpoint | Details |
|---------|----------|---------|
| App | `GET /api/health` | Includes DB, cache, worker status |
| AI Service | `GET /health` | LLM provider connectivity |
| Scheduler | `GET /health` | Background task status |
| Worker | `GET /health` | Job processing status |

### Observability

| Endpoint | Description |
|----------|-------------|
| `GET /api/observability/stats` | Overall system metrics |
| `GET /api/observability/metrics` | Prometheus-compatible metrics |
| `GET /api/observability/services/health` | Per-service health |
| `GET /system/services/topology` | Service topology — local vs remote |

### Admin Dashboard

The admin panel (Settings → Services) shows real-time service status with health dot indicators. The `ServerPoolManager` periodically health-checks all registered nodes (every 30 seconds by default) and excludes unhealthy nodes from load balancing.

---

## FULLY_AUTOMATED Warning

> **Never set `FULLY_AUTOMATED=true` in production.** This mode bypasses all human approval gates — missions execute without operator confirmation. Use only in isolated lab/testing environments.

```bash
FULLY_AUTOMATED=false
```

---

## Maintenance

### Database Migrations

Migrations run automatically on app startup via `scripts/start.sh`. For manual control:

```bash
# Check current migration
docker compose exec app alembic current

# Apply pending migrations
docker compose exec app alembic upgrade head

# Rollback one migration
docker compose exec app alembic downgrade -1
```

### Updating

```bash
# Pull latest images and restart
docker compose pull
docker compose up -d

# Or in Swarm:
docker service update --image spectra-app:v2 spectra_app
```

### Versioning

Spectra uses **CalVer** (date-based): `YYYY.MM.DD[.patch]`

```bash
python version.py                # 2026.03.13
python version.py --patch 1      # 2026.03.13.1
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 80/443 in use | Change port mapping in Caddy service or stop conflicting service |
| Database connection fails | Verify `POSTGRES_PASSWORD` matches between `.env` and compose |
| Migrations fail | Check `docker logs spectra-app` for migration errors |
| Setup page not loading | Ensure all services are healthy: `docker compose ps` |
| Caddy TLS errors | Ensure `SPECTRA_DOMAIN` is set and DNS points to this server |
| WebSocket disconnects | Check Caddy logs; verify firewall allows WebSocket upgrades |
| Services can't communicate | Ensure `SERVICE_AUTH_SECRET` is the same across all services |
| Worker not processing jobs | Check `docker logs spectra-worker`; verify DB connectivity |
