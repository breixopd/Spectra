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

## Server Pool Concept

Spectra includes a `ServerPoolManager` (`app/services/scaling/pool_manager.py`) that tracks server nodes across the infrastructure. Each node is stored in the `server_nodes` database table.

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

S3/MinIO is now required in every deployment mode.

- There is no local filesystem fallback for missions, pentest sessions, knowledge assets, or backups.
- Single-host deployments can use the bundled MinIO service; multi-host deployments can use MinIO or any external S3-compatible endpoint.
- Automated backups are S3-native and stored in `S3_BUCKET_BACKUPS` when `BACKUP_ENABLED=true`.

### MinIO Setup (Self-Hosted)

Add MinIO to your Docker Compose:

```yaml
minio:
  image: minio/minio
  command: server /data --console-address ":9001"
  environment:
    MINIO_ROOT_USER: spectra-admin
    MINIO_ROOT_PASSWORD: spectra-secret-key
  volumes:
    - minio_data:/data
  ports:
    - "9000:9000"
    - "9001:9001"
  networks:
    - spectra-network
```

Configure in `.env`:

```bash
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=spectra-admin
S3_SECRET_KEY=spectra-secret-key
S3_BUCKET_MISSIONS=spectra-missions
S3_BUCKET_SESSIONS=spectra-sessions
S3_BUCKET_KNOWLEDGE=spectra-knowledge
S3_BUCKET_BACKUPS=spectra-backups
```

### Cloud S3 Migration

To migrate from MinIO to cloud S3:

1. Update `.env` with cloud credentials:
   ```bash
   S3_ENDPOINT_URL=https://s3.amazonaws.com
   S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
   S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   S3_REGION=us-east-1
   ```
2. Migrate existing data using `mc mirror` (MinIO Client) or `aws s3 sync`
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
