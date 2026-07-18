# Deployment Guide

[← Wiki Home](Home.md) | [Operations](operations.md) | [Configuration](configuration.md) | [Scaling](scaling.md) | [Security](security.md)

---

Complete guide for deploying Spectra in production — from single-server Docker Compose to multi-host Docker Swarm with Cloudflare and Caddy.

**Deployment modes:**

- **Docker Compose** — single-server or small teams. Use `docker compose up --scale` for deliberate/manual replica changes; the production auto-scaler is Swarm-only.
- **Docker Swarm** (recommended for production) — multi-host rolling updates, encrypted overlay networking, Swarm secrets, and the supported automatic scaling/auto-heal backend. Operators add hosts with the Swarm bootstrap script and use the Admin UI for visibility/control.
- **Kubernetes** is not supported.

S3-compatible object storage is part of the runtime contract. Missions, pentest sessions, knowledge assets, and backups are stored in S3; there is no local filesystem fallback.

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
| **ai-svc** | `spectra-ai` | 5010 | LLM routing, embeddings, RAG | 1 |
| **scheduler** | `spectra-scheduler` | 5011 | Background jobs, backups, metrics, sandbox watchdog | 1+ (leader-elected) |
| **worker** | `spectra-worker` | 5012 | Tool execution (manages ephemeral sandbox containers) | 1–3 |
| **db** | `spectra-db` | 5432 | PostgreSQL + pgvector (persistent state, PostgreSQL-backed app cache, job queue, LISTEN/NOTIFY backbone) | 1 |
| **redis** | `spectra-redis` | 6379 | Shared distributed rate-limiting backend | 1 |
| **caddy** | `spectra-caddy` | 80/443 | Reverse proxy — TLS, security headers | 1 |
| **garage** | `spectra-garage` | 3900 | Self-hosted S3-compatible object storage (required unless you point to external S3) | 0–1 |
| **tensorzero** | `spectra-tensorzero` | 3000 | AI gateway — provider-agnostic model routing, observability, optimization | 1 |
| **clickhouse** | `spectra-clickhouse` | 8123 | Analytics and inference storage for TensorZero | 1 |

See [Topology](topology.md) for visual architecture diagrams.

### Inter-Service Communication

All services communicate using:

- **PostgreSQL** for persistent state, PostgreSQL-backed app cache, job queue (`SELECT ... FOR UPDATE SKIP LOCKED`), and pub/sub (`NOTIFY`/`LISTEN`)
- **HTTP + shared secret** (`X-Service-Auth` header) for direct service-to-service API calls
- **Redis** as the shared distributed rate-limiting backend

`RATE_LIMIT_STORAGE=memory://` is acceptable for tests or intentionally ephemeral local runs, but it is not the normal deployment recommendation. Keep Redis so rate-limit counters stay shared across app replicas. Use Caddy rate limiting only if you intentionally want all rate limiting to live at the edge.

### Sandbox Containers

Each mission gets one ephemeral sandbox container (Kali Linux) for tool execution. The worker service manages these containers via Docker socket. Sandboxes are auto-cleaned after mission completion — no need for additional tools containers.

---

## Quick Start (Single Server)

### 1. Prepare the Server

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL "https://download.docker.com/linux/$(. /etc/os-release && echo "${ID}")/gpg" -o /tmp/docker.asc
sudo mv /tmp/docker.asc /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME:-$UBUNTU_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "${USER}"
sudo mkdir -p /opt/spectra && sudo chown "${USER}:${USER}" /opt/spectra
cd /opt/spectra
git clone <repo-url> .
```

Open a new shell before running `docker` without `sudo` so the new group membership is applied.

### 2. Configure Environment

```bash
cat > .env <<'EOF'
# --- Required ---
POSTGRES_PASSWORD=<generate with: openssl rand -hex 16>
JWT_SECRET_KEY=<generate with: openssl rand -hex 32>
SERVICE_AUTH_SECRET=<generate with: openssl rand -hex 32>
# One-time administrator enrollment token (never commit or log this value).
# Generate it first: openssl rand -base64 48 | tr -d '/+='; paste the output here.
SPECTRA_SETUP_TOKEN=replace-with-a-random-enrollment-token

# --- Domain (for Caddy TLS) ---
PLATFORM_DOMAIN=spectra.example.com

# --- AI Provider (TensorZero) ---
TENSORZERO_GATEWAY_URL=http://tensorzero:3000

# --- Security (optional; default is autonomous) ---
# REQUIRE_APPROVAL=true

# --- Required S3/Garage ---
GARAGE_ACCESS_KEY=spectra
GARAGE_SECRET_KEY=<generate with: openssl rand -hex 16>
S3_ENDPOINT_URL=http://garage:3900
S3_ACCESS_KEY=spectra
S3_SECRET_KEY=<same as GARAGE_SECRET_KEY>
EOF
```

See [Configuration](configuration.md) for all available settings.

### 3. Deploy (All Services)

```bash
# All services (microservices mode by default)
docker compose -f deploy/docker/compose.yaml --profile app up -d
```

This starts all services as separate containers with health checks:

- `spectra-app` — Core API + Web UI
- `spectra-ai` — AI/LLM service
- `spectra-scheduler` — Background tasks
- `spectra-worker` — Tool execution
- `spectra-db` — PostgreSQL
- `spectra-caddy` — Reverse proxy
- `spectra-tensorzero` — AI gateway (routes LLM requests to providers)
- `spectra-clickhouse` — Analytics storage for TensorZero

### 4. Setup Wizard

Open the Caddy URL (`http://your-server:${SPECTRA_PORT:-15080}` for local Compose, or
`https://spectra.example.com` when a domain is configured). The app container port is
loopback-bound by default and should not be treated as a public endpoint. First visit
redirects to `/setup` → paste the one-time `SPECTRA_SETUP_TOKEN` generated by
`scripts/first_run.sh` (or provisioned as the Swarm `spectra_setup_token` secret), then
create the admin account.

### 5. Verify

```bash
# Check all containers are healthy
docker compose -f deploy/docker/compose.yaml ps

# Process liveness (cheap; used by Caddy and container probes)
curl -f "http://localhost:${SPECTRA_PORT:-15080}/api/healthz"

# Dependency readiness (returns 503 until the compute plane is ready)
curl -f "http://localhost:${SPECTRA_PORT:-15080}/api/health/ready"

# Public platform status shape (API, DB, storage, AI, worker, scheduler)
curl -f "http://localhost:${SPECTRA_PORT:-15080}/api/v1/health?scope=public" | python3 -m json.tool

# Full detail, including service latency and scaled nodes (admin JWT or service auth)
curl -f -H "X-Service-Auth: ${SERVICE_AUTH_SECRET}" \
  "http://localhost:${SPECTRA_PORT:-15080}/api/v1/health?detail=full&include=services,nodes" | python3 -m json.tool

# Tail logs
docker compose -f deploy/docker/compose.yaml logs -f app
```

---

## Operations Runbooks

Deployment bootstrap and first verification stay on this page. For ongoing runbooks, use [Operations](operations.md) as the canonical owner and [scripts/ops/README.md](../../scripts/ops/README.md) for the local script catalog.

After the stack is up:

- Run `./scripts/health_check.sh 'http://<host>/api/healthz'` for the first liveness smoke check, followed by `/api/v1/health?scope=public` for dependency status.
- For compose/staging validation, run `START_STACK=1 ./scripts/test.sh live-smoke`. It starts the test stack, bootstraps Garage buckets without printing secrets, runs setup/login if needed, checks public and full health latency, tests TensorZero, and smoke-tests UI routes. Set `APP_BASE_URL` to point the same smoke at a deployed VPS or Swarm manager.
- Confirm backup visibility via **Admin UI → Backups** or `GET /api/admin/backups` once storage is configured.
- Use [Deployment](deployment.md#rollback) for version rollback mechanics if the rollout needs to be reversed.

---

## Auto-Scaling Configuration

Auto-scaling is opt-in and disabled by default. To enable it, add to your `.env`:

```bash
AUTOSCALE_ENABLED=true
AUTOSCALE_WORKER_MIN=1
AUTOSCALE_WORKER_MAX=10
AUTOSCALE_QUEUE_THRESHOLD=10
AUTOSCALE_COOLDOWN_SECS=300
```

Automatic scaling is supported only by the Docker Swarm backend:

- **Docker Compose**: use `docker compose up --scale` for deliberate/manual replica changes; it does not run automatic scaling decisions.
- **Docker Swarm** (recommended): scales services via `docker service scale` and can auto-heal failed tasks. Add hosts to the pool via **Admin UI → Scaling tab** before enabling it.

After initial configuration, scaling is fully hands-off. The scheduler's capacity monitor evaluates metrics every 60 seconds and adjusts replicas automatically. See [Scaling](scaling.md#auto-scaling) for the full configuration reference and per-service policy details.

### Resource Calculations

The `ResourceManager` (`packages/scaling/src/spectra_scaling/resource_manager.py`) calculates how many sandbox containers each node can support based on available memory, CPU, and configured resource tiers. The capacity monitor uses these calculations for utilization alerts and auto-scaling decisions.

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
    reverse_proxy app:5000 {
        health_uri /api/healthz
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

The main Compose file (`deploy/docker/compose.yaml`) is pre-configured with:

- Resource limits on all containers
- Garage for S3 storage (internal only, no exposed ports)
- Caddy reverse proxy
- All volumes persisted

For production, create a `.env.prod` with required secrets and use:

```bash
docker compose -f deploy/docker/compose.yaml --env-file .env.prod --profile app up -d
```

### Required Environment Variables

| Variable | Why Required |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database authentication |
| `JWT_SECRET_KEY` | Token signing — sessions invalidate on restart if unset |
| `SERVICE_AUTH_SECRET` | Inter-service authentication (microservices mode) |
| `SPECTRA_SETUP_TOKEN` | One-time `/setup` enrollment token; required for production setup |
| `PLATFORM_DOMAIN` | TLS certificate provisioning via Let's Encrypt |
| `GARAGE_SECRET_KEY` | S3 storage authentication (if Garage is used) |

### SSL/TLS with Caddy

| Feature | Details |
|---------|---------|
| **TLS termination** | Auto-provisioned Let's Encrypt certificates |
| **Security headers** | CSP, HSTS (63072000s, preload), X-Frame-Options DENY |
| **WebSocket proxy** | Automatic upgrade detection and proxying |
| **Health checks** | Polls `/api/healthz` for proxy liveness; use `/api/health/ready` for full dependency readiness |
| **Timeouts** | 300s read/write for long-running operations |

Set `PLATFORM_DOMAIN` in `.env`:

```bash
PLATFORM_DOMAIN=spectra.example.com
```

When using `localhost`, Caddy serves on port 443 with a self-signed certificate.

---

## Production: Docker Swarm (Multi-Server)

Docker Swarm is built into Docker Engine — no extra software to install. Use it when you need multiple hosts, rolling updates, or secret management.

A pre-built Swarm stack is at `deploy/docker/docker-compose.swarm.yml`.

Swarm now mirrors the Compose runtime contract: `ai-svc` on `5010`, `scheduler` on `5011`, and `worker` on `5012`. The stack also supports `_FILE` secret environment variables such as `POSTGRES_PASSWORD_FILE`, `SERVICE_AUTH_SECRET_FILE`, and `JWT_SECRET_KEY_FILE`. **Scheduler** and **worker** HTTP healthchecks include a **`start_period` of 90s** so cold starts during rolling updates are less likely to be marked unhealthy before dependencies are ready.

### 1. Initialize Swarm

```bash
# On the manager node:
docker swarm init --advertise-addr <MANAGER_IP>

# Save the join token from the output, then on each worker node:
docker swarm join --token <TOKEN> <MANAGER_IP>:2377
```

**Firewall / exposure (non-negotiable):** do **not** publish Swarm control-plane ports (**2377/tcp**, **7946/tcp+udp**, **4789/udp** for overlay) to the public Internet. Put managers and workers on a **private network** or **WireGuard / site-to-site VPN**, join using the **VPN IP** as `--advertise-addr` / join target, and restrict host firewalls (or cloud security groups) so only **SSH (key-only, allowlisted)** and **HTTP/S to Caddy** are reachable from untrusted networks. Remote Docker for provisioning should use **SSH + TLS** or API sockets bound to **loopback + VPN**, not raw `0.0.0.0:2375`.

### 2. Label Nodes

Assign roles so services land on the right hardware. Labels use per-role booleans
so a single node can host multiple roles (e.g. `app` + `db` on the same host):

```bash
# Per-role labels (a node can have several)
docker node update --label-add spectra.app=true <APP_NODE_HOSTNAME>
docker node update --label-add spectra.db=true  <DB_NODE_HOSTNAME>
docker node update --label-add spectra.worker=true <WORKER_NODE_HOSTNAME>
docker node update --label-add spectra.ai=true  <GPU_NODE_HOSTNAME>    # Optional: GPU node for local LLM

# Example: small deployment — one node runs everything
for role in app db ai worker; do
  docker node update --label-add spectra.$role=true <NODE_HOSTNAME>
done
```

### 3. Create Secrets

Swarm secrets are encrypted at rest and only available to services that reference them:

Create `.env` with `VERSION`, registry settings, and secret source values, then let the deployment helper create the exact external secrets required by `deploy/docker/docker-compose.swarm.yml`:

```bash
./scripts/ops/swarm_deploy.sh --secrets
./scripts/ops/swarm_deploy.sh --preflight
```

Required Swarm secrets are: `db_password`, `db_url`, `service_auth`, `jwt_secret`, `secret_key`, `encryption_key`, `spectra_setup_token`, `redis_password`, `garage_access_key`, `garage_secret_key`, `garage_rpc_secret`, `garage_admin_token`, `clickhouse_password`, `openai_api_key`, and `anthropic_api_key`.

### 4. Create Configs

```bash
docker config create caddyfile docker/Caddyfile.prod
```

### 5. Deploy the Stack

```bash
./scripts/ops/swarm_deploy.sh --deploy
```

### 6. Verify

```bash
# List all services and their replica status
docker service ls

# Check a specific service
docker service ps spectra_app

# Follow logs
docker service logs spectra_app --follow

# Health checks (Caddy ingress; app is not publicly published)
curl -f http://<MANAGER_IP>/api/healthz
curl -f 'http://<MANAGER_IP>/api/v1/health?scope=public'
```

### Swarm Service Layout

The `docker-compose.swarm.yml` defines these services with placement constraints:

| Service | Placement | Replicas | Secrets |
|---------|-----------|----------|---------|
| `db` | `node.labels.spectra.db == true` | 1 | `db_password` |
| `app` | `node.labels.spectra.app == true` | 2 | `db_url`, `db_password`, `service_auth`, `jwt_secret`, `secret_key`, `encryption_key`, `redis_password`, Garage secrets |
| `ai-svc` | `node.labels.spectra.ai == true` | 1 | `db_url`, `service_auth`, `secret_key`, `encryption_key`, `redis_password`, Garage secrets |
| `scheduler` | `node.role == manager` | 1 | `db_url`, `service_auth`, `secret_key`, `encryption_key`, `redis_password`, Garage secrets |
| `worker` | `node.labels.spectra.worker == true` | 2 | `db_url`, `service_auth`, `redis_password`, Garage secrets |
| `caddy` | `node.labels.spectra.app == true` | 1 | — (uses config) |

The `frontend` and `backend` overlay networks span Swarm nodes automatically and are configured with encrypted overlay driver options. `backend` remains internal.

### Rolling Updates

Swarm performs zero-downtime updates by default:

```bash
# Update the app image across all replicas
docker service update --image spectra-app:v2 spectra_app

# The swarm.yml configures: parallelism=1, delay=10s, order=start-first
# So one replica updates while the other continues serving traffic.
```

---

## Self-Hosted Image Registry

For Swarm deployments across multiple nodes, every node must be able to pull the Spectra images. A self-hosted Docker registry removes external dependencies and lets you distribute custom worker images across the cluster.

### Why Self-Host?

- **No external dependency** — images stay on your network, no Docker Hub rate limits
- **Required for multi-node Swarm** — worker nodes need to pull images from somewhere
- **Custom worker images** — build and push images with additional tools pre-installed

### Setting Up a Docker Registry

Deploy a registry as a standalone container or Swarm service:

```bash
# Standalone container (simplest)
docker run -d -p 5050:5000 --restart=always \
  -v registry:/var/lib/registry \
  --name registry registry:2
```

For TLS (recommended in production), mount certificates:

```bash
docker run -d -p 5050:5000 --restart=always \
  -v registry:/var/lib/registry \
  -v /path/to/certs:/certs \
  -e REGISTRY_HTTP_TLS_CERTIFICATE=/certs/domain.crt \
  -e REGISTRY_HTTP_TLS_KEY=/certs/domain.key \
  --name registry registry:2
```

For local/lab environments without TLS, configure each Docker daemon to allow insecure access (see below).

### Building and Pushing Images

```bash
cd /path/to/spectra

# Build all images
docker build -t <registry>:5050/spectra-app:latest -f deploy/docker/Dockerfile.api .
docker build -t <registry>:5050/spectra-ai-svc:latest -f deploy/docker/Dockerfile.ai .
docker build -t <registry>:5050/spectra-scheduler:latest -f deploy/docker/Dockerfile.scheduler .
docker build -t <registry>:5050/spectra-caddy:latest -f deploy/docker/Dockerfile.caddy .
docker build -t <registry>:5050/spectra-worker:latest -f deploy/docker/Dockerfile.worker .

# Push all
for img in spectra-app spectra-ai-svc spectra-scheduler spectra-caddy spectra-worker; do
  docker push <registry>:5050/$img:latest
done
```

Replace `<registry>` with the IP or hostname of the node running your registry.

### Configuring Nodes to Use the Registry

**Insecure (HTTP) registry** — add to `/etc/docker/daemon.json` on every Swarm node:

```json
{
  "insecure-registries": ["<registry-ip>:5050"]
}
```

Then restart Docker: `sudo systemctl restart docker`

**TLS registry** — distribute the CA certificate to each node:

```bash
sudo mkdir -p /etc/docker/certs.d/<registry-ip>:5050
sudo cp ca.crt /etc/docker/certs.d/<registry-ip>:5050/
```

### Using the Registry in Swarm Deploys

Set `REGISTRY` in your `.env` before deploying:

```bash
REGISTRY=<registry-ip>:5050/
```

The compose files use the `${REGISTRY:-}spectra-app:${VERSION:-latest}` pattern, so the registry prefix is applied to all image references automatically.

```bash
docker stack deploy -c deploy/docker/docker-compose.swarm.yml spectra
```

### Custom Libraries and Modules

Spectra does not have custom pip packages to host — all Python dependencies come from `requirements/*.txt` and are baked into the Docker images at build time. The only custom assets to distribute are:

- **Docker images** (via the registry above)

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
2. Paste the contents of `deploy/docker/compose.yaml` (or the swarm file for multi-host)
3. Under **Environment variables**, add `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `SERVICE_AUTH_SECRET`, `PLATFORM_DOMAIN`, etc.
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
docker compose -f deploy/docker/compose.yaml --profile app up -d --scale app=3

# Docker Swarm:
docker service scale spectra_app=3
```

PostgreSQL still carries persistent state, the PostgreSQL-backed app cache, the job queue, and WebSocket event flow via `LISTEN`/`NOTIFY`. Redis remains the shared distributed rate-limiting backend across app replicas.

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
# Self-hosted MinIO (included in compose.yaml):
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
| App | `GET /api/healthz` / `GET /api/health/ready` | Cheap process liveness / dependency readiness |
| AI Service | `GET /health` | LLM provider connectivity |
| Scheduler | `GET /health` | Background task status |
| Worker | `GET /health` | Job processing status |

### Observability

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/observability/stats` | Overall system metrics |
| `GET /api/v1/observability/metrics` | Prometheus-compatible metrics |
| `GET /api/v1/observability/services/health` | Per-service health |
| `GET /system/services/topology` | Service topology — local vs remote |

### Admin Dashboard

The admin panel (Settings → Services) shows real-time service status with health dot indicators. The `ServerPoolManager` periodically health-checks all registered nodes (every 30 seconds by default) and excludes unhealthy nodes from load balancing.

---

## Human-in-the-loop (`REQUIRE_APPROVAL`)

> By default, missions run autonomously. End users choose whether to pause for approval on risky steps via **Profile → Mission Defaults** and optional launch checkboxes on the dashboard. For a **platform-wide emergency**, operators set **`REQUIRE_APPROVAL=true`** in the service environment (or Swarm) so every high/critical action escalates — this is **not** stored in `system_config` or the Admin UI.

```bash
REQUIRE_APPROVAL=true
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
docker compose -f deploy/docker/compose.yaml --profile app up -d

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
| Caddy TLS errors | Ensure `PLATFORM_DOMAIN` is set and DNS points to this server |
| WebSocket disconnects | Check Caddy logs; verify firewall allows WebSocket upgrades |
| Services can't communicate | Ensure `SERVICE_AUTH_SECRET` is the same across all services |
| Worker not processing jobs | Check `docker logs spectra-worker`; verify DB connectivity |
