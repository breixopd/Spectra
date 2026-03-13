# Deployment Guide

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Scaling](scaling.md) | [Security](security.md)

---

Complete guide for deploying Spectra in production — from single-server Docker Compose to multi-host orchestration with Portainer, Docker Swarm, or Kamal.

## Choosing a Deployment Method

| Method | Best For | Complexity | Multi-Host |
|--------|----------|------------|------------|
| **Docker Compose** | Single server, dev/staging | Low | No |
| **Portainer** | Visual management, 1–5 hosts | Low | Yes (via agent) |
| **Docker Swarm** | Built-in clustering, 2–10 hosts | Medium | Yes |
| **Kamal** | Zero-downtime SSH deploys | Medium | Yes |
| **Kubernetes** | >10 nodes, auto-scaling, multi-cloud | High | Yes |

Most Spectra deployments run well on a single server with Docker Compose. Graduate to Portainer or Swarm when you need multi-host or a web UI for operations.

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

---

## Recommended: Portainer

Portainer Community Edition is a free web UI for managing Docker containers, images, volumes, and networks across one or many hosts. It requires zero YAML knowledge for day-to-day operations.

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

1. In Portainer, go to **Stacks → Add stack**.
2. Paste the contents of `docker/docker-compose.prod.yml`.
3. Under **Environment variables**, add `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `SPECTRA_DOMAIN`, etc.
4. Click **Deploy the stack**.

Portainer provides:

| Feature | Details |
|---------|---------|
| **Container management** | Start/stop/restart/remove from the UI |
| **Logs** | Stream container logs in-browser |
| **Resource usage** | CPU and memory per container, real-time |
| **Stack updates** | Edit compose YAML and redeploy in one click |
| **Image management** | Pull, tag, and push images from the UI |
| **Multi-host** | Manage all Docker hosts from a single dashboard |

### Portainer Stack Template for Spectra

Save a reusable template in Portainer's **App Templates**:

```yaml
# Spectra stack template — paste into Portainer
version: "3.8"

services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: spectra
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: spectra
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U spectra"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    image: registry.yourdomain.com/spectra/app:${VERSION:-latest}
    expose: ["5000"]
    depends_on:
      db: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+asyncpg://spectra:${POSTGRES_PASSWORD}@db:5432/spectra
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      SPECTRA_DOMAIN: ${SPECTRA_DOMAIN}
      AI_PROVIDER: ${AI_PROVIDER:-litellm}
      LLM_API_KEY: ${LLM_API_KEY}
      FULLY_AUTOMATED: "false"
    volumes:
      - spectra_data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/api/health"]
      interval: 15s
      timeout: 5s
      retries: 5

  caddy:
    image: caddy:2-alpine
    ports: ["443:443", "80:80"]
    volumes:
      - ./Caddyfile.prod:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on:
      app: { condition: service_healthy }

  tools:
    image: registry.yourdomain.com/spectra/tools:${VERSION:-latest}
    depends_on:
      db: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+asyncpg://spectra:${POSTGRES_PASSWORD}@db:5432/spectra
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      IS_TOOLS_CONTAINER: "true"
      PLUGIN_SAFE_MODE: "true"
    volumes:
      - spectra_data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    cap_add: [NET_ADMIN, NET_RAW]

volumes:
  postgres_data:
  spectra_data:
  caddy_data:
```

---

## Alternative: Docker Swarm

Docker Swarm is built into Docker Engine — no extra installation needed. It gives you replicas, rolling updates, health-check-based restart, and load balancing.

### Initialize Swarm

```bash
# On the manager node
docker swarm init --advertise-addr <MANAGER_IP>

# Output gives you a join token. On each worker node:
docker swarm join --token SWMTKN-1-xxxx <MANAGER_IP>:2377
```

### Deploy Spectra as a Swarm Stack

```bash
# From the manager node, in the Spectra repo
docker stack deploy -c docker/docker-compose.prod.yml spectra
```

### Scale Services

```bash
# Scale the app to 3 replicas (Swarm load-balances automatically)
docker service scale spectra_app=3

# Scale tool workers for more parallel scans
docker service scale spectra_tools=5

# Check service status
docker service ls
docker service ps spectra_app
```

### Rolling Updates

```bash
# Update the app image with zero downtime
docker service update \
  --image registry.yourdomain.com/spectra/app:v2.1.0 \
  --update-parallelism 1 \
  --update-delay 30s \
  spectra_app
```

### Why Swarm Over Kubernetes

| Swarm | Kubernetes |
|-------|------------|
| Built into Docker — `docker swarm init` and you're running | Requires installing a distribution (k3s, k8s, EKS, etc.) |
| Same compose YAML you already have | Needs Deployments, Services, Ingress, ConfigMaps, Secrets |
| 5 minutes to set up | Hours to days for production readiness |
| Replicas + failover + rolling updates | Same, plus auto-scaling, service mesh, CRDs |
| Works for 2–10 node clusters | Designed for 10–1000+ nodes |

For Spectra's typical deployment (1–5 nodes), Swarm provides everything needed without the operational overhead of Kubernetes.

### Swarm Networking

Swarm creates an overlay network automatically. Services communicate by name:

```bash
# Inside any container in the stack:
curl http://spectra_app:5000/api/health
curl http://spectra_db:5432
```

### Health Checks and Auto-Restart

Swarm uses the `healthcheck` from compose to detect unhealthy containers and automatically restarts them. The health checks in `docker-compose.prod.yml` are already configured correctly.

---

## Alternative: Kamal

[Kamal](https://kamal-deploy.org/) (by 37signals / Basecamp) deploys Docker containers to any server over SSH. No cluster manager, no orchestrator daemon — just SSH + Docker.

### Install

```bash
gem install kamal
```

### Configure

Create `config/deploy.yml` in the Spectra repo:

```yaml
service: spectra
image: registry.yourdomain.com/spectra/app

servers:
  web:
    hosts:
      - 203.0.113.10
      - 203.0.113.11
    labels:
      traefik.http.routers.spectra.rule: Host(`spectra.example.com`)
  worker:
    hosts:
      - 203.0.113.12
    cmd: python -m app.worker

registry:
  server: registry.yourdomain.com
  username: spectra
  password:
    - KAMAL_REGISTRY_PASSWORD

env:
  clear:
    DATABASE_URL: postgresql+asyncpg://spectra:PASSWORD@db-host:5432/spectra
    AI_PROVIDER: litellm
    FULLY_AUTOMATED: "false"
  secret:
    - JWT_SECRET_KEY
    - LLM_API_KEY
    - POSTGRES_PASSWORD

accessories:
  db:
    image: pgvector/pgvector:pg16
    host: 203.0.113.10
    port: 5432
    env:
      clear:
        POSTGRES_USER: spectra
        POSTGRES_DB: spectra
      secret:
        - POSTGRES_PASSWORD
    directories:
      - data:/var/lib/postgresql/data

healthcheck:
  path: /api/health
  port: 5000
```

### Deploy

```bash
# First-time setup (installs Docker on all servers)
kamal setup

# Subsequent deployments
kamal deploy

# Rollback
kamal rollback
```

### Why Kamal

- Zero-downtime deploys out of the box.
- Great migration path: start with 1 server, add more by listing hosts.
- Uses Traefik for load balancing (auto-configured).
- Same Docker images, no cluster infrastructure.

---

## When to Graduate to Kubernetes

Kubernetes adds significant operational complexity. For Spectra, consider Kubernetes only when you need:

| Requirement | Why Kubernetes Helps |
|-------------|---------------------|
| Auto-scaling across >10 nodes | HPA + Cluster Autoscaler |
| Complex service mesh (mTLS, traffic splitting) | Istio / Linkerd |
| Multi-cloud / hybrid deployment | Federation, cloud-agnostic abstractions |
| Fine-grained RBAC for infrastructure teams | Kubernetes RBAC, namespaces |
| GPU scheduling for local LLM inference | Node selectors, device plugins |

For most Spectra deployments (single team, 1–5 servers, <100 concurrent users), Portainer or Docker Swarm covers the need. See the [Microservices Split](microservices-split.md) document for the full Kubernetes manifest examples planned for later phases.

### Lightweight K8s: k3s

If you do need Kubernetes, start with [k3s](https://k3s.io/) — a single-binary distribution:

```bash
# Install k3s on the server (includes kubectl, containerd, Traefik)
curl -sfL https://get.k3s.io | sh -

# Deploy Spectra
kubectl apply -f k8s/
```

---

## Spectra-Specific Deployment Notes

### Service Architecture

Spectra consists of these core services:

| Service | Image | Required | Purpose |
|---------|-------|----------|---------|
| **db** | `pgvector/pgvector:pg16` | Yes | PostgreSQL + pgvector for RAG |
| **app** | `spectra-app` | Yes | FastAPI API + Web UI on port 5000 |
| **caddy** | `caddy:2-alpine` | Production | TLS termination, reverse proxy |
| **tools** | `spectra-tools` | For scans | Kali Linux worker for security tools |
| **minio** | `minio/minio` | Optional | S3-compatible object storage |

### Microservices Mode

For higher-scale deployments, Spectra supports splitting the monolith into separate services using `docker/docker-compose.services.yml`:

```bash
# Start in microservices mode (API + AI + Scheduler as separate containers)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.services.yml up -d
```

This splits the app into:
- **spectra-api** — Core API (port 5000)
- **spectra-ai-svc** — AI/LLM service (port 5010, internal)
- **spectra-scheduler** — Background tasks (no port)
- **spectra-worker** — Tool execution (already separate)

See [Microservices Split](microservices-split.md) for full details.

### Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_PASSWORD` | Yes | — | Database password |
| `JWT_SECRET_KEY` | Yes | — | JWT signing key |
| `SPECTRA_DOMAIN` | Production | `localhost` | Domain for TLS |
| `AI_PROVIDER` | No | `litellm` | LLM provider backend |
| `LLM_API_KEY` | If using API LLM | — | API key for LLM provider |
| `FULLY_AUTOMATED` | No | `false` | Bypass human approval (lab only) |
| `PLUGIN_SAFE_MODE` | No | `true` | Restrict plugin capabilities |
| `SANDBOX_ORCHESTRATOR_URL` | No | — | Remote sandbox service URL |
| `LLM_GATEWAY_URL` | No | — | Remote LLM gateway URL |

### Deploy with Each Method — Summary

```bash
# === Docker Compose (single server) ===
docker compose -f docker/docker-compose.prod.yml up -d

# === Portainer ===
# 1. Install Portainer, 2. Add stack via UI with docker-compose.prod.yml

# === Docker Swarm ===
docker swarm init
docker stack deploy -c docker/docker-compose.prod.yml spectra
docker service scale spectra_app=3

# === Kamal ===
kamal setup   # first time
kamal deploy  # subsequent
```
