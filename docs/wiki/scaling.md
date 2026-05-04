# Scaling

[← Wiki Home](home.md) | [Operations](operations.md) | [Architecture](architecture.md) | [Configuration](configuration.md) | [API Reference](api-reference.md)

---

Guide to scaling Spectra across multiple servers — server pools, required S3-compatible storage, sandbox workers, and health monitoring.

## Single-Server Mode (Default)

By default, everything runs on a single host via Docker Compose. No gateway URLs need to be set. The `ServiceRegistry` automatically uses in-process implementations.

```bash
# .env — single-server (default)
# No gateway URLs needed
```

---

## Scaling Individual Services

Each Spectra service runs in its **own container image** (with `SERVICE_MODE` set
for shared configuration such as DB pool sizing). Horizontal scale adjusts
**replicas** of that image — not router modes on a single process. See
[microservices-split](microservices-split.md) for how the Core API differs from
AI / worker / scheduler entrypoints.

### Scaling Workers

Workers are the most common scaling target. Multiple worker instances safely share the job queue via `SELECT ... FOR UPDATE SKIP LOCKED`.

When auto-scaling is enabled (`AUTOSCALE_ENABLED=true`), worker replicas are adjusted automatically based on queue depth. For manual scaling:

```bash
# Docker Compose
docker compose -f docker/compose.yaml up -d --scale worker=3
```

```yaml
# Docker Swarm (replicas managed automatically when auto-scaling is on)
services:
  worker:
    deploy:
      replicas: 3
```

### Scaling AI Service

For high LLM throughput, scale the AI service:

```bash
docker compose -f docker/compose.yaml up -d --scale ai-svc=2
```

The app service routes AI requests to `AI_SERVICE_URL`. With multiple replicas behind Docker's internal DNS round-robin, requests are distributed automatically.

### Scheduler — Leader Election (Safe Multi-Replica)

The scheduler uses **PostgreSQL advisory lock-based leader election** (`pg_try_advisory_lock`). Multiple scheduler replicas can run safely — only the one that acquires the global leader lock (`_SCHEDULER_LEADER_LOCK_ID`) starts background tasks. Other replicas stand by and retry every 15 seconds, taking over automatically if the leader fails.

Individual tasks (backups, DB maintenance, stale job recovery, exploit DB refresh, Docker cleanup) each use their own advisory locks, providing an additional layer of protection against duplicate execution even during leader transitions.

### Scaling the Core API

Scale the API service for more web/API capacity:

```bash
docker compose -f docker/compose.yaml up -d --scale app=2
```

When scaling the API, ensure Caddy (or your reverse proxy) load-balances across all API instances.

---

## Server Pool Concept

Spectra includes a `ServerPoolManager` (`spectra_platform/services/scaling/pool_manager.py`) that tracks server nodes across the infrastructure. Each node is stored in the `server_nodes` database table.

### ServerNode Model

| Field | Type | Description |
|-------|------|-------------|
| `service_type` | string | `sandbox_worker`, `db`, `storage` |
| `name` | string | Human-readable node name |
| `url` | string | Node endpoint URL |
| `is_active` | bool | Whether the node accepts work |
| `is_primary` | bool | For DB: primary vs replica |
| `weight` | int | Load balancing weight (higher = more traffic) |
| `max_capacity` | int | Max concurrent tasks |
| `current_load` | int | Current active tasks |
| `health_status` | string | `healthy`, `unhealthy`, `unknown` |
| `last_health_check` | datetime | Last health check timestamp |
| `metadata` | JSON | Extra per-node configuration |

### Weighted Least-Connections Load Balancing

When selecting a node for a task, the pool manager uses weighted least-connections:

1. Filter active, healthy nodes for the requested `service_type`
2. Filter nodes with available capacity (`current_load < max_capacity`)
3. Score each node: `current_load / weight` (lower is better)
4. Select from best-scoring nodes (ties broken randomly for distribution)

---

## Adding Sandbox Workers

### Via Admin API

```bash
# Add a sandbox worker node
curl -X POST /api/admin/servers \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "service_type": "sandbox_worker",
    "name": "tools-server-1",
    "url": "http://192.168.1.50:9090",
    "weight": 2,
    "max_capacity": 20
  }'
```

### Via SSH Auto-Provisioning

From the admin panel → Services tab:

1. **Verify** (`POST /api/admin/servers/verify`) — test SSH connectivity
2. **Provision** (`POST /api/admin/servers/provision`) — install Docker, pull Spectra images, start the service, verify health
3. **Deprovision** (`POST /api/admin/servers/deprovision`) — stop and remove the service

```json
{
  "host": "192.168.1.50",
  "port": 22,
  "username": "root",
  "private_key": "...",
  "service_type": "sandbox_worker",
  "service_port": 9090
}
```

### Via Environment Variable

For a single remote sandbox orchestrator:

```bash
SANDBOX_ORCHESTRATOR_URL=http://tools-server:9090
SANDBOX_ORCHESTRATOR_API_KEY=sk-sandbox-key
```

---

## S3-Compatible Storage

S3-compatible storage is now required in every deployment mode.

- There is no local filesystem fallback for missions, pentest sessions, knowledge assets, or backups.
- Single-host deployments can use the bundled Garage service; multi-host deployments can use Garage or any external S3-compatible endpoint.
- Automated backups are S3-native and stored in the `spectra-backups` bucket (configured via `S3_BUCKET_BACKUPS`) when `BACKUP_ENABLED=true`.

### Garage Setup (Self-Hosted)

Add Garage to your Docker Compose:

```yaml
garage:
  image: dxflrs/garage:v2.2.0
  volumes:
    - ./garage.toml:/etc/garage.toml:ro
    - garage_meta:/var/lib/garage/meta
    - garage_data:/var/lib/garage/data
  ports:
    - "3900:3900"
    - "3903:3903"
  networks:
    - spectra-network
```

Configure in `.env`:

```bash
S3_ENDPOINT_URL=http://garage:3900
S3_ACCESS_KEY=spectra
S3_SECRET_KEY=your-garage-secret-key
# Bucket names below use hardcoded defaults; override only for custom setups
# S3_BUCKET_MISSIONS=spectra-missions
# S3_BUCKET_SESSIONS=spectra-sessions
# S3_BUCKET_KNOWLEDGE=spectra-knowledge
# S3_BUCKET_BACKUPS=spectra-backups
```

### Cloud S3 Migration

To migrate from Garage to cloud S3:

1. Update `.env` with cloud credentials:
   ```bash
   S3_ENDPOINT_URL=https://s3.amazonaws.com
   S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
   S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   S3_REGION=us-east-1
   ```
2. Migrate existing data using `aws s3 sync` or equivalent tooling
3. Restart the app container

Works with any S3-compatible provider: AWS S3, Cloudflare R2, DigitalOcean Spaces, Google Cloud Storage (S3-compatible mode).

### S3 Buckets

| Bucket | Purpose |
|--------|---------|
| `spectra-missions` | Mission scan artifacts, output files |
| `spectra-sessions` | Pentest session data |
| `spectra-knowledge` | Knowledge base documents, CVE data |
| `spectra-backups` | Database backups |

The backup service reads and writes directly from S3. Use [Operations](operations.md) for the canonical backup, restore, storage health, and logging runbook entry points.

---

## Database Scaling

### Read Replicas

Add read replicas as `db` service type nodes:

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

### Managed Database

For production, consider a managed PostgreSQL service with pgvector support:

- AWS RDS for PostgreSQL (with pgvector extension)
- Supabase
- Neon

Update `DATABASE_URL` to point to the managed instance and enable SSL:

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/spectra?sslmode=require
```

---

## Admin API Endpoints

All server pool endpoints require superuser authentication.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/servers` | List all server nodes |
| `POST` | `/api/admin/servers` | Register a new server node |
| `DELETE` | `/api/admin/servers/{id}` | Remove a server node |
| `PATCH` | `/api/admin/servers/{id}` | Update server node properties |
| `POST` | `/api/admin/servers/health-check` | Trigger health check on all nodes |
| `POST` | `/api/admin/servers/verify` | Test SSH connectivity to a remote server |
| `POST` | `/api/admin/servers/provision` | Auto-install service on remote server |
| `POST` | `/api/admin/servers/deprovision` | Remove service from remote server |

See [API Reference](api-reference.md) for request/response schemas.

---

## Health Monitoring

### Service Health Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /system/services/health` | Health check all registered services (local + remote) |
| `GET /system/services/topology` | Current topology — which services are local vs remote |
| `GET /api/health` | Basic app health (used by Caddy and deploy scripts) |

### Automatic Health Checks

The `ServerPoolManager` periodically health-checks all registered nodes (default: every 30 seconds). Unhealthy nodes are excluded from load balancing until they recover.

For the operator triage flow after a health check fails, use [Operations](operations.md).

### Monitoring Metrics

Available via the observability endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/observability/stats` | Overall system metrics |
| `GET /api/v1/observability/metrics` | Prometheus-style metrics |
| `GET /api/v1/observability/services/health` | Per-service health |

---

## Auto-Scaling

Spectra includes a reactive auto-scaling engine (`spectra_platform/services/scaling/auto_scaler.py`) that monitors queue depth and service utilization to automatically adjust replica counts. Auto-scaling works with both Docker Compose and Docker Swarm; **Docker Swarm is the recommended production deployment** because it handles multi-host replica placement automatically.

### How It Works

1. The scheduler's `capacity_monitor` loop runs every 60 seconds
2. When `AUTOSCALE_ENABLED=true`, the `AutoScaler` collects metrics (queue depth, replica counts, utilization)
3. Per-service `ScalingPolicy` objects define thresholds that trigger scale-up or scale-down decisions
4. Decisions execute via `docker service scale` (Swarm) or `docker compose up --scale` (Compose)
5. A cooldown period prevents thrashing between scale actions
6. Admins add new hosts via **Admin UI → Scaling tab**; the engine handles the rest

After initial setup — enabling auto-scaling and adding hosts to the server pool — scaling is fully hands-off.

**Auto-heal (Swarm):** when the collector reports Swarm tasks in **`failed`** or **`rejected`** state (or very recent failures in the task history), the scheduler may restart the affected service. **`failed_tasks` is not** `desired_replicas - running_tasks`, so brief replica gaps during rolling updates do not count as failures.

### Per-Service Scaling Policies

| Service | Min | Max | Scale-Up Trigger | Scale-Down Trigger | Max Rationale |
|---------|-----|-----|------------------|--------------------|---------------|
| **Worker** | `AUTOSCALE_WORKER_MIN` (1) | `AUTOSCALE_WORKER_MAX` (10) | Queue depth > `AUTOSCALE_QUEUE_THRESHOLD` | Queue idle for `AUTOSCALE_IDLE_SECS` | Each worker uses 4 GB+; diminishing returns beyond 10 |
| **API** | `AUTOSCALE_API_MIN` (1) | `AUTOSCALE_API_MAX` (8) | Utilization > 85% | Utilization < 20% for idle period | Connection pool becomes bottleneck at 8 × 20 = 160 connections |
| **AI** | 1 | `AUTOSCALE_AI_MAX` (4) | Utilization > 80% | Utilization < 20% for idle period | Bounded by upstream LLM rate limits |
| **Scheduler** | 1 | 2 | Leader failure (automatic failover) | N/A | Leader election (`pg_try_advisory_lock`); second replica is hot standby only |

Workers scale proportionally to queue depth (e.g., depth 30 with threshold 10 scales up by 3). Other services scale by one replica per evaluation.

### Infrastructure Monitoring (Not Scaling)

Database, Redis, and S3 are **monitored** by the infrastructure monitor but are **not auto-scaled** — they require operator-managed topology changes. The monitor sends alerts when utilization approaches configured thresholds:

| Component | Threshold Setting | Default | Alert |
|-----------|-------------------|---------|-------|
| PostgreSQL | `INFRA_MONITOR_PG_THRESHOLD` | 80% | Connection pool near capacity |
| Redis | `INFRA_MONITOR_REDIS_THRESHOLD` | 85% | Memory near limit |
| S3 / Garage | `INFRA_MONITOR_STORAGE_THRESHOLD` | 90% | Disk usage high |

Enable with `INFRA_MONITOR_ENABLED=true`. Alerts go to `NOTIFICATION_WEBHOOK`.

### Adding Nodes via Admin UI

1. Go to **Admin Panel → Scaling** tab
2. Click **Add Server** and provide the host address + SSH credentials
3. Select the service type (`sandbox_worker`, `db`, etc.)
4. Spectra verifies connectivity, provisions Docker + images, and starts the service
5. The node joins the server pool and the auto-scaler begins using it automatically

### Configuration

All settings are initial defaults from environment variables. After first boot, the **Admin UI is the source of truth** — changes made in the UI are persisted to the database and override `.env` values.

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTOSCALE_ENABLED` | `false` | Enable auto-scaling (opt-in) |
| `AUTOSCALE_WORKER_MIN` | `1` | Minimum worker replicas |
| `AUTOSCALE_WORKER_MAX` | `10` | Maximum worker replicas |
| `AUTOSCALE_API_MIN` | `1` | Minimum API replicas |
| `AUTOSCALE_API_MAX` | `8` | Maximum API replicas |
| `AUTOSCALE_AI_MAX` | `4` | Maximum AI service replicas |
| `AUTOSCALE_QUEUE_THRESHOLD` | `10` | Queue depth to trigger worker scale-up |
| `AUTOSCALE_COOLDOWN_SECS` | `300` | Minimum seconds between scale actions |
| `AUTOSCALE_IDLE_SECS` | `300` | Seconds of idle before scale-down |
| `AUTOSCALE_CPU_UP_THRESHOLD` | `75` | CPU % to trigger scale-up |
| `AUTOSCALE_CPU_DOWN_THRESHOLD` | `25` | CPU % to trigger scale-down |
| `INFRA_MONITOR_ENABLED` | `true` | Enable infrastructure monitoring |
| `INFRA_MONITOR_PG_THRESHOLD` | `80` | PostgreSQL connection pool alert threshold (%) |
| `INFRA_MONITOR_REDIS_THRESHOLD` | `85` | Redis memory alert threshold (%) |
| `INFRA_MONITOR_STORAGE_THRESHOLD` | `90` | Storage disk alert threshold (%) |
| `SWARM_WORKER_SERVICE` | `spectra_worker` | Docker service name for worker |
| `SWARM_API_SERVICE` | `spectra_app` | Docker service name for API |
| `SWARM_AI_SERVICE` | `spectra_ai-svc` | Docker service name for AI |
| `SWARM_SCHEDULER_SERVICE` | `spectra_scheduler` | Docker service name for scheduler |

### Capacity Alerts

Even without auto-scaling enabled, the capacity monitor tracks `ServerNode` utilization and sends alerts:
- **Warning** at 80% utilization
- **Critical** when at full capacity

Alerts are sent via the configured `NOTIFICATION_WEBHOOK`.

See [Topology](topology.md) for visual architecture diagrams.

---

## Deployment Topologies

### 1. Single-Server (Default)

All services on one host with bundled MinIO or an external S3 endpoint. No gateway URLs set.

### 2. Split Tools

Dedicate a server to sandbox workers. App + DB stay on primary.

```bash
SANDBOX_ORCHESTRATOR_URL=http://tools-server:9090
SANDBOX_ORCHESTRATOR_API_KEY=sk-sandbox-key
```

### 3. Full Distributed

App + dedicated sandbox workers + S3 storage + DB replicas.

```bash
SANDBOX_ORCHESTRATOR_URL=http://tools-server:9090
SANDBOX_ORCHESTRATOR_API_KEY=sk-sandbox-key
S3_ENDPOINT_URL=http://minio-server:9000
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
```

### Configuring Gateway URLs

Gateway URLs can be set via:

| Method | When |
|--------|------|
| `.env` file | Before first boot |
| Setup wizard (`/setup`) | During initial configuration (Service Topology step) |
| Admin panel → Services tab | Runtime changes (takes effect immediately) |

---

## Auto-Migration Features

### SSH Auto-Provisioning

The admin panel provides one-click provisioning for remote servers:

1. Provide SSH credentials (host, port, username, password or key)
2. Select service type (`sandbox_worker`)
3. Spectra installs Docker, pulls images, starts the service, and verifies health

### Golden Image Distribution

When plugins change, the golden `spectra-tools` image is automatically rebuilt. For multi-server setups:

- **Phase 1:** Local Docker `registry:2` container — images stay local
- **Phase 2:** Harbor (self-hosted with scanning) or GHCR — images distributed to remote nodes

Remote servers pull the updated image on next sandbox creation.
