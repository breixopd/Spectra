# Configuration

[← Wiki Home](home.md) | [Architecture](architecture.md) | [Deployment](deployment.md) | [Scaling](scaling.md)

---

All Spectra configuration options, organized by section. Settings are loaded from environment variables and `.env` files via Pydantic Settings.

AI provider, model, API keys, and routing settings are configured through the **web UI** at `/setup` on first launch and stored in the database. The variables below serve as initial defaults.

---

## Core

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_NAME` | str | `"Spectra"` | Application name |
| `DEBUG` | bool | `false` | Enable debug mode |
| `LOG_LEVEL` | str | `"INFO"` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `SECRET_KEY` | str | `"change-me-in-production"` | General secret key (auto-generated if default) |

---

## JWT Authentication

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `JWT_SECRET_KEY` | SecretStr | `""` | Secret key for JWT tokens. Auto-generated if empty or placeholder. Set for stable sessions across restarts |
| `ENCRYPTION_KEY` | str | `""` | Separate key for encrypting MFA TOTP secrets and credentials. Falls back to `JWT_SECRET_KEY` if not set. Set explicitly to isolate signing and encryption key domains |
| `JWT_ALGORITHM` | str | `"HS256"` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `1440` | Token lifetime in minutes (default: 24 hours) |

---

## AI / LLM

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `TENSORZERO_GATEWAY_URL` | str | `""` | TensorZero gateway URL (e.g. `http://tensorzero:3000`) |
| `TENSORZERO_API_KEY` | str | `""` | API key passed to TensorZero gateway (for provider auth) |
| `LLM_TIMEOUT` | float | `600.0` | LLM request timeout (seconds) |
| `EMBEDDING_MODEL` | str | `"local/BAAI/bge-small-en-v1.5"` | Model for RAG embeddings (see [Embeddings](#embeddings) below) |

Model routing and fallback chains are configured in the TensorZero gateway config (`config/tensorzero.toml`), not via environment variables.

---

### Embeddings

Spectra supports two embedding backends:

| Mode | `EMBEDDING_MODEL` value | Requirements |
|------|------------------------|--------------|
| **Local (default)** | `local/BAAI/bge-small-en-v1.5` | None — fastembed downloads the model on first use |
| **API** | Any model name (e.g. `text-embedding-3-small`) | `EMBEDDING_API_KEY` |

**Local embeddings** use [fastembed](https://github.com/qdrant/fastembed) with ONNX-optimized models.
The model is **lazy-loaded** — it is only downloaded on the first `embed()` call. If you
configure an API-backed model instead, the local model is never fetched and uses zero disk space.

Any model supported by fastembed can be used with the `local/` prefix, e.g. `local/BAAI/bge-base-en-v1.5`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `EMBEDDING_MODEL` | str | `"local/BAAI/bge-small-en-v1.5"` | Embedding model (prefix `local/` for fastembed) |
| `EMBEDDING_API_KEY` | SecretStr | `""` | API key for embedding provider (falls back to `LLM_API_KEY`) |
| `EMBEDDING_API_BASE_URL` | str | `""` | Base URL for embedding API (falls back to `LLM_API_BASE_URL`) |

---

## Database (PostgreSQL)

PostgreSQL is the primary persistent state store, PostgreSQL-backed app cache, job queue, and `LISTEN`/`NOTIFY` backbone.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DATABASE_URL` | SecretStr | `"postgresql+asyncpg://spectra:spectra@db:5432/spectra"` | Async database connection URL |
| `DATABASE_ECHO` | bool | `false` | Echo SQL queries to logs |
| `DATABASE_POOL_SIZE` | int | `20` | Connection pool size |
| `DATABASE_MAX_OVERFLOW` | int | `10` | Max overflow connections beyond pool size |

---

## Rate Limiting

Rate limiting lives in the application layer. PostgreSQL is the persistent state store, PostgreSQL-backed app cache, job queue, and `LISTEN`/`NOTIFY` backbone. Redis is the shared distributed rate-limiting backend.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RATE_LIMIT_STORAGE` | str | `"redis://redis:6379/0"` | Rate-limit backend. The deployment default is Redis so counters stay shared across app replicas. `memory://` is mainly for tests or intentionally ephemeral local runs. Use Caddy rate limiting instead only if you intentionally want rate limiting to live entirely at the edge. |

---

## Object Storage (S3-compatible)

S3-compatible object storage is required for mission data, sessions, knowledge base, and backups. Use the bundled Garage service or an external S3-compatible provider; there is no local filesystem fallback.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `S3_ENDPOINT_URL` | str | `""` | S3-compatible endpoint (e.g., `http://garage:3900`) |
| `S3_ACCESS_KEY` | str | `""` | Access key ID |
| `S3_SECRET_KEY` | SecretStr | `""` | Secret access key |
| `S3_REGION` | str | `"us-east-1"` | S3 region |
| `S3_BUCKET_MISSIONS` | str | `"spectra-missions"` | Bucket for mission artifacts (auto-created by garage-init.sh) |
| `S3_BUCKET_SESSIONS` | str | `"spectra-sessions"` | Bucket for pentest sessions (auto-created by garage-init.sh) |
| `S3_BUCKET_KNOWLEDGE` | str | `"spectra-knowledge"` | Bucket for knowledge base (auto-created by garage-init.sh) |
| `S3_BUCKET_BACKUPS` | str | `"spectra-backups"` | Bucket for database backups (auto-created by garage-init.sh) |

See [Scaling](scaling.md) for Garage setup and cloud S3 migration.

---

## Sandbox Pool

Per-mission ephemeral containers. See [Sandboxes](sandboxes.md) for design details.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SANDBOX_IMAGE` | str | `"spectra-tools"` | Docker image for sandbox containers |
| `SANDBOX_NETWORK` | str | `"spectra-network"` | Docker network for sandboxes |
| `SANDBOX_MAX_CONTAINERS` | int | `10` | Maximum concurrent sandbox containers |
| `SANDBOX_MEMORY_LIMIT` | str | `"2g"` | Default memory limit per sandbox |
| `SANDBOX_CPU_SHARES` | int | `512` | Default CPU shares per sandbox |
| `SANDBOX_MAX_LIFETIME` | int | `7200` | Max sandbox lifetime (seconds) |
| `SANDBOX_IDLE_TIMEOUT` | int | `600` | Destroy sandbox if no heartbeat for this long (seconds) |
| `SANDBOX_HEARTBEAT_INTERVAL` | int | `30` | Worker heartbeat interval (seconds) |
| `SANDBOX_WORKER_POLL_DELAY` | float | `0.5` | Worker queue poll delay (seconds) |
| `SANDBOX_NETWORK_ISOLATION` | bool | `true` | Enable per-sandbox network isolation |
| `SANDBOX_PER_USER_LIMIT` | int | `3` | Max concurrent sandboxes per user |
| `SANDBOX_DEFAULT_PRIORITY` | int | `5` | Default job priority (1=highest, 10=lowest) |

### Resource Tiers

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SANDBOX_RESOURCE_TIERS` | JSON str | See below | Resource tier definitions |
| `SANDBOX_OOM_ESCALATION_ENABLED` | bool | `true` | Auto-escalate tier on OOM (exit 137) |

Default tiers:

| Tier | Memory | CPU Shares |
|------|--------|------------|
| light | 512m | 256 |
| medium | 2g | 512 |
| heavy | 4g | 1024 |
| extreme | 8g | 2048 |

### Warm pool

Target warm idle containers follow **active `sandbox_worker`** entries in `server_nodes` (capped at 10). With **no** worker hosts registered, a small fallback applies for single-host development.

### Image management

Golden images rebuild when plugins change (`PLUGIN_UPDATED`); this is not configurable via env/DB. **Grype** scans run after each successful build when Grype is installed.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL` | bool | `false` | Block promoting the image if critical CVEs are found |

---

## External Services

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SANDBOX_ORCHESTRATOR_URL` | str | `None` | External sandbox orchestrator URL (e.g., `http://orchestrator:8084`) |
| `SANDBOX_ORCHESTRATOR_TIMEOUT` | int | `30` | Orchestrator request timeout (seconds) |
| `SANDBOX_ORCHESTRATOR_API_KEY` | SecretStr | `""` | API key for sandbox orchestrator |

When gateway URLs are empty, services run in-process (default monolith mode). See [Scaling](scaling.md) for multi-server deployment.

---

## Security

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `REQUIRE_APPROVAL` | bool | `false` | **Operator-only emergency:** When `true`, high/critical actions always escalate for human approval. Not persisted in Admin UI or DB; set via environment / Swarm. End users configure defaults under Profile → Mission Defaults; per-launch overrides are on the dashboard. |

See [Security](security.md) for full security model.

---

## CORS

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CORS_ORIGINS` | list[str] | `["http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:5050", "http://127.0.0.1:5050"]` | Allowed CORS origins (comma-separated string or JSON array) |

---

## Platform

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PLATFORM_DOMAIN` | str | `""` | Public domain (e.g., `spectra.example.com`) |
| `PLATFORM_BASE_URL` | str | `""` | Full base URL (e.g., `https://spectra.example.com`) |
| `PLATFORM_EXPOSED` | bool | `false` | Whether platform is accessible from the internet |

---

## VPN

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `VPN_CONFIG_DIR` | str | `"/spectra_platform/vpn_configs"` | Directory for VPN configuration files |
| `VPN_ENABLED` | bool | `true` | Enable VPN support |
| `VPN_AUTO_CONNECT` | str | `""` | Reserved for future use |

---

## Networking

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CONNECT_BACK_HOST` | str | `"spectra-app"` | Worker or callback-relay hostname embedded into connect-back payloads. It must not point at API/Caddy control-plane infrastructure in production. |
| `SHELL_ROUTING_MODE` | str | `"direct"` | Callback listener routing mode. Production API services should use `proxy` and fail closed; worker services may use `direct`. |
| `SHELL_LISTEN_HOST` | str | `"127.0.0.1"` | Worker-side listener bind host. Use `0.0.0.0` only on worker/callback-relay services that are isolated from control-plane networks. |

Custom PoC execution and managed callback listeners are controlled by mission capability policy, plan entitlements, verified scope, and audit logging. They are not controlled by deployment-wide environment kill switches.

---

## Notifications

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `NOTIFICATION_WEBHOOK` | str | `None` | Webhook URL for notifications (e.g., `https://ntfy.sh/your-topic`) |

---

## Runtime Settings

Some settings can be changed at runtime through the web UI (Admin panel → Settings). These are persisted to the database and override environment variables. The database is the source of truth after initial setup; environment variables serve only as initial defaults.

**What belongs where**

| Layer | Examples | Rationale |
| ----- | ---------- | --------- |
| **End users** | Notification prefs, default scan mode, BYOK keys | User-owned preferences (`user_preferences`) |
| **Platform admin** | Domains, webhooks, sandbox limits, scaling thresholds | Capacity, integrations, compliance posture |
| **Emergency (env)** | `REQUIRE_APPROVAL` kill-switch only | Overrides UI — requires deployment access |
| **Deployment only** | Internal image names, queue wiring, DB URLs, Swarm secrets | Never duplicated as “fake” toggles in the UI — set via env / secrets |

Platform behavior that is always on (exploit DB initialization when the service starts, golden-image verification, image vulnerability scans when tooling is present) is **not** exposed as a switch — operators tune timeouts and policies, not “enable the product.”

Admin-UI-manageable settings include:

- `LOG_LEVEL`, `CONNECT_BACK_HOST`
- `NOTIFICATION_WEBHOOK`
- `PLATFORM_DOMAIN`, `PLATFORM_BASE_URL`, `PLATFORM_EXPOSED`
- All `AUTOSCALE_*` and `INFRA_MONITOR_*` settings (via Scaling tab)
- `BACKUP_ENABLED`, `BACKUP_SCHEDULE_HOURS`, `BACKUP_RETENTION_COUNT`

AI/LLM settings are managed through the database-backed `SystemConfig` and are not saved to the runtime file.

When a setting is changed via the Admin UI, all running replicas are notified via PostgreSQL `LISTEN`/`NOTIFY` and re-hydrate their in-memory settings automatically — no restart required.

---

## Deployment Mode

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SCHEDULER_ENABLED` | bool | `true` | Set `false` when running a dedicated scheduler service to prevent maintenance loops from running twice in the main app |
| `ENCRYPTION_KEY` | str | `""` | See Security section above |

---

## Auto-Scaling

Auto-scaling is opt-in and disabled by default. See [Scaling](scaling.md#auto-scaling) for architecture and policy details.

> **Note:** Environment variables below serve as initial defaults. After first boot, the **database** (managed via Admin UI → Scaling tab) is the source of truth. Changes made in the Admin UI override `.env` values.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTOSCALE_ENABLED` | bool | `false` | Enable reactive auto-scaling |
| `AUTOSCALE_WORKER_MIN` | int | `1` | Minimum worker replicas |
| `AUTOSCALE_WORKER_MAX` | int | `10` | Maximum worker replicas (4 GB+ each; diminishing returns beyond 10) |
| `AUTOSCALE_API_MIN` | int | `1` | Minimum API replicas |
| `AUTOSCALE_API_MAX` | int | `8` | Maximum API replicas (connection pool bottleneck at 8 × 20 = 160 conns) |
| `AUTOSCALE_AI_MAX` | int | `4` | Maximum AI service replicas (bounded by upstream LLM rate limits) |
| `AUTOSCALE_QUEUE_THRESHOLD` | int | `10` | Queue depth to trigger worker scale-up |
| `AUTOSCALE_COOLDOWN_SECS` | int | `300` | Minimum seconds between scale actions |
| `AUTOSCALE_IDLE_SECS` | int | `300` | Seconds of idle before scale-down |
| `AUTOSCALE_CPU_UP_THRESHOLD` | int | `75` | CPU % to trigger scale-up |
| `AUTOSCALE_CPU_DOWN_THRESHOLD` | int | `25` | CPU % to trigger scale-down |
| `SWARM_WORKER_SERVICE` | str | `"spectra_worker"` | Docker service name for workers |
| `SWARM_API_SERVICE` | str | `"spectra_app"` | Docker service name for API |
| `SWARM_AI_SERVICE` | str | `"spectra_ai-svc"` | Docker service name for AI |
| `SWARM_SCHEDULER_SERVICE` | str | `"spectra_scheduler"` | Docker service name for scheduler |

---

## Infrastructure Monitoring

Infrastructure monitoring tracks DB, Redis, and storage health and sends alerts when thresholds are approached. These components are **not auto-scaled** — alerts inform operators to take manual action.

> **Note:** Like auto-scaling settings, these serve as initial defaults and can be managed via Admin UI after first boot.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `INFRA_MONITOR_ENABLED` | bool | `true` | Enable infrastructure monitoring |
| `INFRA_MONITOR_PG_THRESHOLD` | int | `80` | PostgreSQL connection pool alert threshold (%) |
| `INFRA_MONITOR_REDIS_THRESHOLD` | int | `85` | Redis memory alert threshold (%) |
| `INFRA_MONITOR_STORAGE_THRESHOLD` | int | `90` | Storage disk usage alert threshold (%) |

---

## Automated Maintenance

These settings control the scheduler's recurring maintenance tasks.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DB_MAINTENANCE_INTERVAL` | int | `604800` | DB VACUUM ANALYZE interval in seconds (default: 7 days) |
| `STALE_JOB_RECOVERY_INTERVAL` | int | `300` | Stale job recovery interval in seconds (default: 5 min) |
| `EXPLOIT_DB_REFRESH_HOURS` | int | `168` | Exploit DB refresh interval in hours (default: 7 days) |
| `DOCKER_CLEANUP_INTERVAL` | int | `604800` | Docker resource pruning interval in seconds (default: 7 days) |
