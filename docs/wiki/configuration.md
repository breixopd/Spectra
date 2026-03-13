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
| `JWT_ALGORITHM` | str | `"HS256"` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `1440` | Token lifetime in minutes (default: 24 hours) |

---

## AI / LLM

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AI_PROVIDER` | str | `"litellm"` | Provider: `litellm` (all models), `ollama`, `mock` (testing) |
| `OLLAMA_HOST` | str | `"http://ai:11434"` | Ollama server URL |
| `OLLAMA_MODEL` | str | `"qwen2.5:3b"` | Default Ollama model |
| `OLLAMA_ENABLED` | bool | `false` | Whether Ollama is available as secondary provider |
| `LLM_API_KEY` | SecretStr | `""` | API key for cloud LLM provider |
| `LLM_API_BASE_URL` | str | `None` | OpenAI-compatible API endpoint URL |
| `LLM_MODEL` | str | `"gpt-4o-mini"` | Default LLM model |
| `LLM_TIMEOUT` | float | `600.0` | LLM request timeout (seconds) |

### Per-Tier Model Routing

Override the default model for specific task complexity tiers. Leave empty to use `LLM_MODEL` for all tiers.

| Variable | Tier | Use Cases |
|----------|------|-----------|
| `LLM_TIER1_MODEL` | Simple | Scope parsing, tool selection, safety checks |
| `LLM_TIER2_MODEL` | Balanced | Planning, steering, reporting |
| `LLM_TIER3_MODEL` | Capable | Exploit crafting, PoC generation |

### Advanced Routing

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AI_PROVIDER_PROFILES` | dict | `{}` | Named provider profiles with model/endpoint configs |
| `AI_PROVIDER_ROUTING` | dict | `{}` | Task-to-profile routing rules |
| `AI_PROVIDER_FALLBACKS` | dict | `{}` | Fallback chains per profile |
| `EMBEDDING_MODEL` | str | `"local/BAAI/bge-small-en-v1.5"` | Model for RAG embeddings (see [Embeddings](#embeddings) below) |

---

### Embeddings

Spectra supports two embedding backends:

| Mode | `EMBEDDING_MODEL` value | Requirements |
|------|------------------------|--------------|
| **Local (default)** | `local/BAAI/bge-small-en-v1.5` | None — fastembed downloads the model on first use |
| **API** | Any model name (e.g. `text-embedding-3-small`) | `LLM_API_KEY` or `EMBEDDING_API_KEY` |

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

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DATABASE_URL` | SecretStr | `"postgresql+asyncpg://spectra:spectra@db:5432/spectra"` | Async database connection URL |
| `DATABASE_ECHO` | bool | `false` | Echo SQL queries to logs |
| `DATABASE_POOL_SIZE` | int | `20` | Connection pool size |
| `DATABASE_MAX_OVERFLOW` | int | `10` | Max overflow connections beyond pool size |

---

## Object Storage (S3/MinIO)

S3-compatible object storage for mission data, sessions, knowledge base, and backups. When empty, falls back to local filesystem.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `S3_ENDPOINT_URL` | str | `""` | MinIO/S3 endpoint (e.g., `http://minio:9000`) |
| `S3_ACCESS_KEY` | str | `""` | Access key ID |
| `S3_SECRET_KEY` | SecretStr | `""` | Secret access key |
| `S3_REGION` | str | `"us-east-1"` | S3 region |
| `S3_BUCKET_MISSIONS` | str | `"spectra-missions"` | Bucket for mission artifacts |
| `S3_BUCKET_SESSIONS` | str | `"spectra-sessions"` | Bucket for pentest sessions |
| `S3_BUCKET_KNOWLEDGE` | str | `"spectra-knowledge"` | Bucket for knowledge base |
| `S3_BUCKET_BACKUPS` | str | `"spectra-backups"` | Bucket for database backups |

See [Scaling](scaling.md) for MinIO setup and cloud S3 migration.

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

### Warm Pool

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SANDBOX_WARM_POOL_ENABLED` | bool | `false` | Pre-warm idle containers for instant assignment |
| `SANDBOX_WARM_POOL_SIZE` | int | `2` | Number of pre-warmed containers to maintain |

### Image Management

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SANDBOX_AUTO_BUILD_IMAGE` | bool | `true` | Auto-rebuild golden image when plugins change |
| `SANDBOX_IMAGE_SCAN_ENABLED` | bool | `true` | Scan golden image for CVEs after each build |
| `SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL` | bool | `false` | Block deployment if critical CVEs found |

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
| `PLUGIN_SAFE_MODE` | bool | `true` | Require Ed25519 signatures on plugins |
| `REQUIRE_APPROVAL` | bool | `false` | Require human approval for high-risk actions |
| `FULLY_AUTOMATED` | bool | `true` | Skip all human approval — fully autonomous operation |

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
| `VPN_CONFIG_DIR` | str | `"/app/vpn_configs"` | Directory for VPN configuration files |
| `VPN_ENABLED` | bool | `true` | Enable VPN support |
| `VPN_AUTO_CONNECT` | str | `""` | Reserved for future use |

---

## Networking

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CONNECT_BACK_HOST` | str | `"spectra-app"` | Hostname tools containers use to reach the app |

---

## Notifications

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `NOTIFICATION_WEBHOOK` | str | `None` | Webhook URL for notifications (e.g., `https://ntfy.sh/your-topic`) |

---

## Runtime Settings

Some settings can be changed at runtime through the web UI (Admin panel → Settings). These are saved to `data/config/runtime_settings.json` and override environment variables on next load:

- `LOG_LEVEL`, `PLUGIN_SAFE_MODE`, `CONNECT_BACK_HOST`
- `REQUIRE_APPROVAL`, `FULLY_AUTOMATED`
- `NOTIFICATION_WEBHOOK`
- `PLATFORM_DOMAIN`, `PLATFORM_BASE_URL`, `PLATFORM_EXPOSED`

AI/LLM settings are managed through the database-backed `SystemConfig` and are not saved to the runtime file.
