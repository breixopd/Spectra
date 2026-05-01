# Deployment

[← Wiki Home](home.md) | [Deployment Guide](deployment-guide.md) | [Operations](operations.md) | [Configuration](configuration.md) | [Scaling](scaling.md)

---

> **Start here for production deployments:** [Deployment Guide](deployment-guide.md) covers Docker Compose, Cloudflare, Docker Swarm, Portainer, scaling, backups, and monitoring. Use [Operations](operations.md) for day-2 runbooks and post-deploy incident handling.

This page covers CI/CD pipeline configuration, per-service builds, and versioning. For first-time setup, see the [Deployment Guide](deployment-guide.md).

Current runtime contract: Docker Compose and Docker Swarm use the same internal service names and ports for the microservices split (`ai-svc:5010`, `scheduler:5011`, `worker:5012`). S3-compatible storage is required for missions, sessions, knowledge, and backups; use bundled Garage or point to an external S3 endpoint.

## Per-Service Builds

Each service has a dedicated Dockerfile. Each image copies only the dependencies and source package surface that service needs:

### Building Individual Services

```bash
# Build a specific service image
docker build -f docker/Dockerfile.api -t spectra-app .
docker build -f docker/Dockerfile.ai -t spectra-ai-svc .
docker build -f docker/Dockerfile.scheduler -t spectra-scheduler .
docker build -f docker/Dockerfile.worker -t spectra-worker .

# Or via docker compose (builds all services)
docker compose -f docker/compose.yaml build
```

### Image Sizes

| Service | Dockerfile | Requirements File | Approx. Size |
|---------|--------|-------------------|--------------|
| **Scheduler** | `docker/Dockerfile.scheduler` | `requirements/scheduler.txt` | ~558 MB |
| **AI Service** | `docker/Dockerfile.ai` | `requirements/ai.txt` | ~1.13 GB |
| **API** | `docker/Dockerfile.api` | `requirements/app.txt` | ~1.34 GB |
| **Worker** | `docker/Dockerfile.worker` | `requirements/worker.txt` | ~4.13 GB |

### Required Environment Variables (Production)

The development Compose file ships weak defaults for rapid local setup. **Override
all** of the following before any shared or production-like deployment:

| Variable | Purpose | Notes |
|----------|---------|-------|
| `POSTGRES_PASSWORD` | Database credential | Swarm: use `_FILE` secret |
| `REDIS_PASSWORD` | Cache / rate-limit store | Swarm: `_FILE` |
| `JWT_SECRET_KEY` | Token signing | Auto-generated in dev; **required** in prod |
| `SECRET_KEY` | Session / CSRF | Same |
| `ENCRYPTION_KEY` | MFA + BYOK encryption | Auto-generated in dev; **required** in prod |
| `SERVICE_AUTH_SECRET` | Inter-service HMAC | Swarm: `_FILE` |
| `GARAGE_ACCESS_KEY` | S3-compatible storage | Replace compose default |
| `GARAGE_SECRET_KEY` | S3-compatible storage | Replace compose default |
| `GARAGE_RPC_SECRET` | Garage cluster comms | Replace compose default |
| `CLICKHOUSE_PASSWORD` | Analytics DB | Empty by default; set if ClickHouse exposed |
| `PLATFORM_DOMAIN` | Caddy TLS + routing | `localhost` default unsafe for public |

See `.env.example` for the full template. Swarm deployments use Docker secrets
(`_FILE` variants) — see [Swarm deployment](#swarm-deployment) below.

### Staging / VPS test parity

After a **clean `git pull`** on the host, mirror the CI unit + coverage gate:

```bash
./scripts/ops/vps-verify-tests.sh
```

The script lives at `scripts/ops/vps-verify-tests.sh` and uses `docker/compose.yaml`
profile `test`. A tree that is missing new tests or still on an old commit can
show **below 70%** aggregate coverage even when `main` is green — always verify
`git rev-parse HEAD` matches the branch you intend.

### SERVICE_MODE Configuration

Each image sets `SERVICE_MODE` (see Dockerfiles) so **shared** code — especially
`app.core.config` (DB pool sizing) and **lifespan** branches in the Core API —
can tell which physical role the container plays (`api`, `ai`, `scheduler`,
`worker`).

**Router mounting** is **not** six variants of one FastAPI app: the AI,
scheduler, and worker processes ship their **own** ASGI entrypoints. Only
`spectra_api` (`Dockerfile.api`) uses `include_routers`, and there the full
surface is loaded for `api`, `all`, or `""`; anything else is health-only (fail
closed). See [Microservices Architecture](microservices-split.md).

```yaml
# Typical split stack (values also baked into Dockerfiles)
services:
  app:
    environment:
      - SERVICE_MODE=api   # Core API — full routers when api|all|""
  ai-svc:
    environment:
      - SERVICE_MODE=ai    # separate spectra_ai.main app
  scheduler:
    environment:
      - SERVICE_MODE=scheduler
  worker:
    environment:
      - SERVICE_MODE=worker
```

For development or single-node runners, `SERVICE_MODE=all` on the **Core API**
process loads the same full router set as `api`.

### Scaling Individual Services

Services can be scaled independently. The most common scaling target is the worker:

```bash
# Scale workers horizontally
docker compose -f docker/compose.yaml up -d --scale worker=3

# Workers use SELECT ... FOR UPDATE SKIP LOCKED, so multiple instances
# naturally distribute jobs without conflicts.
```

In Docker Swarm:

```yaml
services:
  worker:
    deploy:
      replicas: 3
```

The AI service can also be scaled for high LLM throughput. The scheduler should remain at 1 replica to avoid duplicate background tasks.

## Services

| Service | Image | Purpose |
|---------|-------|---------|
| **db** | `pgvector/pgvector:pg16` | PostgreSQL + pgvector (persistent state, PostgreSQL-backed app cache, job queue, LISTEN/NOTIFY backbone, RAG) |
| **redis** | `redis:7-alpine` | Shared distributed rate-limiting backend |
| **caddy** | `ghcr.io/breixopd14/spectra-caddy` | Custom Caddy image from `docker/Dockerfile.caddy` (TLS, security headers, WebSocket, bundled rate-limit module) |
| **app** | `ghcr.io/breixopd14/spectra-app` | FastAPI backend (internal port 5000) |
| **ai-svc** | `ghcr.io/breixopd14/spectra-ai-svc` | AI/LLM service (internal port 5010) |
| **scheduler** | `ghcr.io/breixopd14/spectra-scheduler` | Background tasks (internal port 5011) |
| **worker** | `ghcr.io/breixopd14/spectra-worker` | Tool execution (internal port 5012) |
| **garage** | `dxflrs/garage:v2.2.0` | Self-hosted S3-compatible object storage (required unless external S3 is configured) |

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

cd docker && docker compose up -d
```

- **Dev UI:** `http://localhost:5000`
- Create your admin account at `/setup`
- Configure your AI provider through the web UI
- Health probes:
  - Lightweight: `curl -f 'http://localhost:5000/api/health'`
  - Public platform: `curl -f 'http://localhost:5000/api/v1/health?scope=public'`
  - Full admin/internal: `curl -f -H "X-Service-Auth: $SERVICE_AUTH_SECRET" 'http://localhost:5000/api/v1/health?detail=full&include=services,nodes'`

---

### First-Run Setup

Use the automated first-run script for a complete single-command setup:

```bash
./scripts/first_run.sh
```

This handles:

1. Starting core services (database, Redis, Garage S3)
2. Bootstrapping S3 storage and creating required buckets
3. Running database migrations
4. Starting all application services
5. Printing the setup URL for admin account creation

For a repeatable live smoke test, use:

```bash
# Starts the compose test stack, bootstraps Garage, runs setup/login,
# checks API/UI health, TensorZero, and full health latency.
START_STACK=1 ./scripts/test.sh live-smoke

# Against an existing VPS/Swarm deployment:
APP_BASE_URL=https://spectra.example.com ./scripts/test.sh live-smoke
```

**Manual first-run** (if you prefer step-by-step):

```bash
# 1. Start services
docker compose -f docker/compose.yaml up -d

# 2. Bootstrap S3 storage
bash docker/garage-init.sh

# 3. Copy the printed S3 credentials to your .env file
# 4. Restart to pick up new env vars
docker compose -f docker/compose.yaml restart

# 5. Open /setup in your browser to create the admin account
```

---

## Server Hardening

Before deploying to production, harden the server:

```bash
# On the target server (as root):
sudo ./scripts/ops/harden_server.sh --yes
```

This applies: SSH hardening, UFW firewall, fail2ban, kernel sysctl tuning, and automatic security updates.

## Multi-Node Deployment (Swarm)

```bash
# 1. Initialize Swarm on the manager node
./scripts/ops/swarm_deploy.sh --init

# 2. Label nodes by role
./scripts/ops/swarm_deploy.sh --label <node-id> app
./scripts/ops/swarm_deploy.sh --label <node-id> db

# 3. Deploy the stack
./scripts/ops/swarm_deploy.sh --deploy

# 4. Check status
./scripts/ops/swarm_deploy.sh --status
```

### Adding a New Worker Node

#### Option A: Automated provisioning

```bash
# Get the join token from the manager
docker swarm join-token worker

# Provision and join in one command
./scripts/ops/swarm_deploy.sh provision <new-node-ip> --join-token <token>
```

This automatically:
- Hardens the server (SSH, firewall, fail2ban)
- Installs Docker
- Joins the Swarm cluster

#### Option B: Manual provisioning

1. **Harden the server:**
   ```bash
   scp scripts/ops/harden_server.sh user@new-node:/tmp/
   ssh user@new-node "sudo /tmp/harden_server.sh --yes"
   ```

2. **Install Docker from Docker's apt repository:**
   ```bash
   ssh user@new-node 'bash -se' <<'REMOTE_DOCKER_INSTALL'
   set -euo pipefail
   export DEBIAN_FRONTEND=noninteractive
   sudo apt-get update -qq
   sudo apt-get install -y -qq ca-certificates curl gnupg
   sudo install -m 0755 -d /etc/apt/keyrings
   curl -fsSL "https://download.docker.com/linux/$(. /etc/os-release && echo "${ID}")/gpg" -o /tmp/docker.asc
   sudo mv /tmp/docker.asc /etc/apt/keyrings/docker.asc
   sudo chmod a+r /etc/apt/keyrings/docker.asc
   . /etc/os-release
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME:-$UBUNTU_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
   sudo apt-get update -qq
   sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo systemctl enable docker
   sudo systemctl start docker
   REMOTE_DOCKER_INSTALL
   ```

3. **Open Swarm ports on the new node:**
   ```bash
   ssh user@new-node "sudo ufw allow 2377/tcp && sudo ufw allow 7946/tcp && sudo ufw allow 7946/udp && sudo ufw allow 4789/udp"
   ```

4. **Join the swarm:**
   ```bash
   # On manager: get the token
   docker swarm join-token worker
   
   # On new node: join
   docker swarm join --token <token> <manager-ip>:2377
   ```

5. **Label the node (on manager):**
   ```bash
   docker node ls  # Find the new node ID
   docker node update --label-add spectra.worker=true <node-id>
   ```

6. **Redeploy to spread services:**
   ```bash
   ./scripts/ops/swarm_deploy.sh --deploy
   ```

7. **Verify:**
   ```bash
   ./scripts/ops/swarm_deploy.sh --status
   docker service ls
   docker node ps <node-id>
   ```

For existing Swarm updates, `--deploy` now refuses to mutate the stack unless it can capture both a pre-deploy PostgreSQL backup in `data/backups/` and the currently deployed image tag for rollback. `--rollback` now consumes the recorded previous-version marker plus the deploy-specific backup marker in `.deploy/swarm/` instead of guessing from whichever backup archive happens to be newest.

### Removing a Node

```bash
# 1. Drain the node (moves containers to other nodes)
docker node update --availability drain <node-id>

# 2. Wait for services to migrate
docker node ps <node-id>  # Should show "Shutdown"

# 3. On the worker node: leave the swarm
docker swarm leave

# 4. On the manager: remove the node
docker node rm <node-id>
```

---

## CI/CD Pipeline

### `ci.yml` — Continuous Integration

Triggered on every push/PR to `main` or `develop`.

| Job | Purpose |
|-----|---------|
| **static-analysis** | Single `Dockerfile.test` build, then Ruff, import boundaries, Pyright, Bandit |
| **test** | Unit tests + coverage + settings runner in Docker |
| **integration-test** | Integration pytest suite in Docker (Garage bootstrapped) |
| **docker-build** | Builds runtime images, Trivy CRITICAL gate on images, validates Compose + Swarm config |
| **deps** | `pip-audit` dependency audit |
| **version-check** | Verifies version metadata in `app/_meta/version.py` |
| **compose-smoke** | Push-only: full compose stack + selected e2e/health/performance smoke tests |

### `release.yml` — Build, Push & Deploy

Triggered by **manual dispatch from `main` only**.

1. Validate the operator-supplied CalVer release version
2. Run unit and integration tests in Docker, Bandit on `app/` (HIGH gate), and Compose/Swarm config validation (see `.github/workflows/release.yml` — this path does **not** rerun CI Ruff, import boundaries, or Pyright)
3. Build & push Docker images to GHCR with `latest` + version tags
4. SSH deploy only after the host resolves the currently deployed version and captures a pre-deploy PostgreSQL backup; the post-deploy gate now waits for the unauthenticated `/api/health/ready` probe to confirm database, AI service, TensorZero, scheduler, worker, LLM, and embeddings readiness
5. Publish the git tag and GitHub Release with the generated changelog only after deploy succeeds

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Production server hostname or IP |
| `DEPLOY_USER` | SSH username |
| `DEPLOY_SSH_KEY` | SSH private key for deployment |

---

### Server Migration

To migrate Spectra to a new server:

1. **On the old server — export everything:**
   ```bash
   ./scripts/ops/migrate_server.sh export --output /tmp/spectra-migration
   ```

2. **Transfer to new server:**
   ```bash
   rsync -avz /tmp/spectra-migration/ user@new-server:/tmp/spectra-migration/
   ```

3. **On the new server — set up the base:**
   ```bash
   git clone <repo-url> Spectra && cd Spectra
   cp /tmp/spectra-migration/config/.env .env
   # Edit .env: update PLATFORM_DOMAIN, database passwords, etc.
   ./scripts/first_run.sh
   ```

4. **Import data:**
   ```bash
   ./scripts/ops/migrate_server.sh import --bundle /tmp/spectra-migration
   ```

5. **Verify:**
   ```bash
   ./scripts/ops/migrate_server.sh verify
   ```

---

### Health Checks

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/health` | None | Liveness probe — checks DB, Redis, S3 |
| `GET /api/health?verbose=true` | Required | Detailed status of all components |
| `GET /api/health/ready` | None | Readiness probe — checks DB, AI service, TensorZero, scheduler, worker, LLM, and embeddings |
| `GET /api/health/services` | Required | Aggregate health of all backend microservices |

For monitoring, use the basic endpoint:
```bash
curl -sf http://localhost/api/health | python3 -m json.tool
```

When running multiple replicas, Caddy load-balances health checks across instances. Use `/api/health/services` to check all backend services from any replica.

---

## Rollback

Use this section for rollback mechanics. For the broader operator workflow around validation, logs, backups, and queue cleanup before or after a rollback, see [Operations](operations.md).

### Manual Rollback

```bash
cd /opt/spectra
export VERSION=2026.03.06
docker compose -f docker/compose.yaml pull
docker compose -f docker/compose.yaml up -d
curl -f https://spectra.example.com/api/health
```

### Database Rollback

```bash
docker compose exec app alembic downgrade -1
```
