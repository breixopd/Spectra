# Sandboxes

[← Wiki Home](home.md) | [Scaling](scaling.md) | [Configuration](configuration.md)

---

Per-mission ephemeral sandbox containers — design, lifecycle, security, and resource management.

## Overview

Each mission runs in its own ephemeral Docker container with a dedicated worker. Sandboxes are created lazily on first tool execution and destroyed when the mission reaches a terminal state. The `SandboxPool` service manages the full lifecycle.

---

## Golden Image System

| Layer | Image | Contents |
| ------- | ------- | ---------- |
| Base | `spectra-tools:base` | Dockerfile.tools — Kali + core OS tools (nmap, nikto, sqlmap, etc.) |
| Latest | `spectra-tools:latest` | Base + all plugin tools installed |

**Rebuild trigger**: When plugins change (upload/remove), the golden image is automatically rebuilt (`SANDBOX_AUTO_BUILD_IMAGE=true`).

**Build process**:

1. Parse all `plugins/*.json` → extract install commands
2. Generate ephemeral Dockerfile `FROM spectra-tools:base`
3. `docker build` → tag as `spectra-tools:latest`
4. Docker layer caching keeps unchanged layers fast
5. Background task — sandboxes use existing `:latest` until new build completes

**Image scanning**: Golden images are scanned for CVEs after each build (`SANDBOX_IMAGE_SCAN_ENABLED=true`).

---

## Sandbox Lifecycle

### Creation

```text
Image: spectra-tools:latest
Network: spectra-network
Capabilities: NET_ADMIN, NET_RAW (all others dropped)
Devices: /dev/net/tun
Volumes: reports/missions/{id}/ (rw)
Entrypoint: python -m app.worker --queue=mission_{id}
Resource limits: memory (2GB default), CPU (512 shares default)
Name: spectra-sandbox-{mission_id[:8]}
```

### Lifecycle Flow

1. Mission starts → `MissionExecutionManager.run_mission_loop()`
2. First tool exec → `SandboxPool.create_sandbox(mission_id)`
3. Worker in sandbox listens on mission-specific queue
4. Tools execute as local subprocesses inside the sandbox
5. Results flow through PostgreSQL job queue
6. Mission ends → `SandboxPool.destroy_sandbox(mission_id)`
7. Orphan cleanup: periodic task removes stale `spectra-sandbox-*` containers

---

## Queue & LISTEN/NOTIFY

### Per-Mission Queue Routing

```python
# App side
queue = PostgresJobQueue(queue_name=f"mission_{mission_id}")
job_id = await queue.enqueue_job("execute_tool_job", ...)
# → NOTIFY spectra_jobs_mission_{mission_id}

# Worker side (in sandbox)
await worker_loop(functions, queue_name=f"mission_{mission_id}")
# → LISTEN spectra_jobs_mission_{mission_id}
```

Each sandbox has its own queue. `SKIP LOCKED` ensures atomic job claiming.

---

## Resource Tiers

| Tier | Memory | CPU Shares | Example Tools |
| ------ | -------- | ------------ | --------------- |
| light | 512m | 256 | nmap, whatweb, subfinder |
| medium | 2g | 512 | gobuster, ffuf, nuclei |
| heavy | 4g | 1024 | sqlmap, metasploit, hydra |
| extreme | 8g | 2048 | large-scale scans |

### OOM Escalation

When a tool exits with code 137 (OOM killed), the sandbox is automatically recreated at the next tier up (`SANDBOX_OOM_ESCALATION_ENABLED=true`). Max one escalation to prevent infinite scaling.

---

## Data Persistence

| Data Type | Storage | Survives Sandbox Destruction? |
| ----------- | --------- | ------------------------------- |
| stdout/stderr | Job result in PostgreSQL | Yes |
| Parsed findings | Mission object + DB | Yes |
| Output files (nmap XML, etc.) | S3/MinIO or mounted volume | Yes |
| Mission logs | DB | Yes |
| Tool cache | App container CacheService | Yes (shared) |

### S3 Storage Integration

When `S3_ENDPOINT_URL` is configured, mission artifacts are stored in S3-compatible storage instead of local volumes. This enables multi-server setups where sandboxes run on different hosts.

See [Scaling](scaling.md) for MinIO/S3 setup details.

---

## Wordlist Management

- **Seclists** are baked into the golden image (~700MB, installed via apt)
- Plugin `args_templates` reference `/usr/share/seclists/` paths
- **User wordlists** go on a named volume `spectra_wordlists` mounted read-only into sandboxes
- The app container mounts the same volume read-write for uploads via the API

---

## VPN Integration

VPN config is injected at sandbox creation:

1. Check `mission.vpn_config` — if set, mount config file into sandbox
2. First job enqueued is `vpn_connect_job`
3. Worker connects VPN before any tool jobs execute
4. Each sandbox has its own network namespace — VPN in one sandbox doesn't affect others
5. Sandboxes include `NET_ADMIN`, `NET_RAW` capabilities and `/dev/net/tun`

---

## Security Hardening

### Container Security

- `CAP_DROP ALL` + only `NET_ADMIN`/`NET_RAW` added
- PID limits (`--pids-limit 256`)
- tmpfs for temp space (`--tmpfs /tmp:size=2G`)
- Read-only root filesystem where possible
- No Docker socket mounted in sandboxes
- Default seccomp profile

### Network Isolation

- Each sandbox ideally gets its own Docker network (`spectra-sandbox-{mission_id}`)
- Connected to `spectra-network` only for DB access
- `SANDBOX_NETWORK_ISOLATION=true` enables per-sandbox network isolation
- Prevents sandbox A from targeting sandbox B

### Secrets Segregation

- Sandboxes only receive `DATABASE_URL` (limited-privilege user) and `IS_TOOLS_CONTAINER=true`
- Never: `JWT_SECRET_KEY`, `LLM_API_KEY`, or other app secrets
- Mission-scoped secrets passed as Docker secrets or tmpfs-mounted files

### Audit

All sandbox lifecycle events are logged: create, destroy, crash, VPN connect, tool execution, resource limit hits.

---

## Failure Handling

### Sandbox Crash Recovery

1. `SandboxPool` monitors containers via Docker events API or periodic health checks
2. On crash: mark stuck `in_progress` jobs as `failed`, save checkpoint
3. Auto-restart: create new sandbox → resume from checkpoint (up to 3 retries)
4. After 3 failures: mark mission `paused`, notify user via WebSocket

### Job Reaper

Periodic task reclaims jobs stuck in `in_progress` longer than 2× their timeout.

### Idle Watchdog

Sandboxes are destroyed if no heartbeat is received within `SANDBOX_IDLE_TIMEOUT` (default: 600s). Workers send heartbeats every `SANDBOX_HEARTBEAT_INTERVAL` (default: 30s).

---

## Warm Pool

Pre-warmed idle containers for instant mission start (`SANDBOX_WARM_POOL_ENABLED=false` by default):

- Maintains `SANDBOX_WARM_POOL_SIZE` idle containers ready for assignment
- When a mission requests a sandbox, assign a pre-warmed one
- Spin up a replacement in the background

---

## Configuration

See [Configuration](configuration.md) for all sandbox-related settings. Key settings:

| Setting | Default | Description |
| --------- | --------- | ------------- |
| `SANDBOX_MAX_CONTAINERS` | 10 | Max concurrent sandboxes |
| `SANDBOX_MEMORY_LIMIT` | 2g | Default memory per sandbox |
| `SANDBOX_PER_USER_LIMIT` | 3 | Max sandboxes per user |
| `SANDBOX_MAX_LIFETIME` | 7200 | Max sandbox lifetime (seconds) |
| `SANDBOX_IDLE_TIMEOUT` | 600 | Idle timeout (seconds) |
