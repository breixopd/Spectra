# Per-Mission Ephemeral Sandbox Containers — Design Reference

> **Status**: Future work. Saved from Round 10 planning (2026-03-09) for later implementation.

## 1. Overview

Replace the shared persistent `spectra-tools` container with per-mission ephemeral sandboxes. Each sandbox runs its own worker from a golden image, with tools executing locally inside the sandbox.

**Key decisions:**

- Each sandbox has its **own worker** (no docker exec from outside)
- Per-mission queue routing via `queue_name=mission_{id}`
- Full **LISTEN/NOTIFY** push (replaces polling on both sides)
- **Golden image** rebuilt when plugins change (all tools pre-installed)
- Lazy creation (on first tool exec in a mission)

## 2. Golden Image System

| Layer  | Image                  | Contents                                                            |
| ------ | ---------------------- | ------------------------------------------------------------------- |
| Base   | `spectra-tools:base`   | Dockerfile.tools — Kali + core OS tools (nmap, nikto, sqlmap, etc.) |
| Latest | `spectra-tools:latest` | Base + all plugin tools installed                                   |

**Rebuild trigger**: When plugins change (upload/remove).

**Build process**:

1. Parse all `plugins/*.json` → extract `install_method` + `install_packages`
2. Generate ephemeral Dockerfile `FROM spectra-tools:base`
3. `docker build` → tag as `spectra-tools:latest`
4. Docker layer caching keeps unchanged layers fast
5. Background task — sandboxes use existing `:latest` until new build completes

## 3. Sandbox Lifecycle

- **Created lazily** on first tool execution in a mission
- **Destroyed** when mission reaches terminal state (completed/failed/cancelled)
- **Orphan cleanup**: periodic task removes `spectra-sandbox-*` containers past `max_lifetime`

### SandboxPool.create_sandbox(mission_id)

```
Image: spectra-tools:latest
Network: spectra-network
Capabilities: NET_ADMIN, NET_RAW
Devices: /dev/net/tun
Volumes: reports/missions/{id}/ (rw)
Entrypoint: python -m app.worker --queue=mission_{id}
Resource limits: memory (2GB), CPU (1.0)
Name: spectra-sandbox-{mission_id[:8]}
```

## 4. Queue & LISTEN/NOTIFY Upgrade

### Current state

- `enqueue_job()` sends `NOTIFY spectra_jobs` (already implemented)
- `worker_loop()` **polls** every 1s (doesn't LISTEN)
- `Job.result()` **polls** every 0.5-5s (exponential backoff)

### Target state

**Worker side** — `worker_loop()`:

- `LISTEN spectra_jobs_{queue_name}` via asyncpg
- Wake on notification → claim job → execute
- Fallback to 1s polling if LISTEN connection drops

**App side** — `Job.result()`:

- `LISTEN spectra_job_done_{job_id}` via asyncpg
- Wake on notification → return result
- Worker sends `NOTIFY spectra_job_done_{job_id}` after storing result

**Result**: Zero-latency dispatch AND zero-latency result retrieval.

### Per-mission queue routing

```python
# App side (ToolExecutionService._execute_via_worker)
queue = PostgresJobQueue(queue_name=f"mission_{mission_id}")
job_id = await queue.enqueue_job("execute_tool_job", tool_id=..., target=...)
# → NOTIFY spectra_jobs_mission_{mission_id}

# Worker side (in sandbox)
# python -m app.worker --queue=mission_{mission_id}
await worker_loop(functions, queue_name=f"mission_{mission_id}")
# → LISTEN spectra_jobs_mission_{mission_id}
```

`PostgresJobQueue` already supports custom `queue_name`. `SKIP LOCKED` still used for safety.

## 5. Execution Flow

```
1. Mission starts → MissionExecutionManager.run_mission_loop()
2. Phase/task execution unchanged → ToolSelectorAgent → ToolAction
3. ToolExecutionService.execute_request() → safety/consensus checks (unchanged)
4. First tool exec: ensure_sandbox(mission_id)
   → SandboxPool.create_sandbox() → container starts with worker
5. _execute_via_worker() uses PostgresJobQueue(queue_name="mission_{id}")
6. Worker in sandbox LISTENs → picks up → builds command from plugin config → local subprocess
7. Result → DB → NOTIFY → app gets result immediately
8. Output files in reports/missions/{id}/ (mounted volume)
9. Mission ends → SandboxPool.destroy_sandbox(mission_id)
```

Everything above step 3 is unchanged from the user/agent perspective. The tool execution pipeline retains all safety checks, consensus voting, command building from plugin JSON, and output parsing.

## 6. Data Persistence

| Data type                     | Where stored                            | Survives sandbox destruction? |
| ----------------------------- | --------------------------------------- | ----------------------------- |
| stdout/stderr                 | Job result in PostgreSQL                | Yes                           |
| Parsed findings               | Mission object + DB                     | Yes                           |
| Output files (nmap XML, etc.) | `reports/missions/{id}/` mounted volume | Yes                           |
| Mission logs                  | DB                                      | Yes                           |
| Tool cache                    | App container CacheService              | Yes (shared)                  |

## 7. Reliability

- **Resource limits** per sandbox (memory, CPU) — prevent one mission starving others
- **Sandbox cap**: `SANDBOX_MAX_CONTAINERS` (default 5). Queue missions at capacity.
- **LISTEN/NOTIFY with polling fallback** — graceful degradation
- **Orphan cleanup** — periodic task + max_lifetime enforcement
- **Container health check** before routing first job

## 8. Configuration

```python
SANDBOX_POOL_ENABLED = False  # Feature gate
SANDBOX_MAX_CONTAINERS = 5
SANDBOX_MEMORY_LIMIT = "2g"
SANDBOX_CPU_LIMIT = 1.0
SANDBOX_MAX_LIFETIME = 3600  # seconds
```

## 9. Migration Path

1. Add LISTEN/NOTIFY to `queue.py` (backward compatible with current worker)
2. Build golden image system (`golden_image.py`)
3. Add SandboxPool + per-mission queue routing
4. Remove shared tools container from `docker-compose.yml`
5. Feature gate with `SANDBOX_POOL_ENABLED` during migration

## 10. Files to Create/Modify

| File                                 | Action                                        |
| ------------------------------------ | --------------------------------------------- |
| `app/core/queue.py`                  | LISTEN/NOTIFY upgrade                         |
| `app/worker.py`                      | `--queue` CLI arg                             |
| `app/services/tools/sandbox_pool.py` | **New** — container lifecycle                 |
| `app/services/tools/golden_image.py` | **New** — image management                    |
| `app/services/tools/service.py`      | Per-mission queue routing                     |
| `app/core/constants.py`              | Sandbox config constants                      |
| `docker/docker-compose.yml`          | Remove persistent tools service (behind gate) |
