# Per-Mission Ephemeral Sandbox Containers — Design Reference

## Design Decisions

### Q1: How will wordlists work — shared cache, baked into image, or hybrid?

**Decision**: Hybrid — seclists baked into the golden image, custom/user wordlists on a shared read-only Docker volume.

**Rationale**: `Dockerfile.tools` already installs `seclists` via apt (~700MB installed). Docker layer caching means the disk cost is O(1) regardless of sandbox count. Plugin `args_templates` already hardcode `/usr/share/seclists/` paths, so no code changes needed. User-uploaded wordlists (via `/api/wordlists/upload`) go on a named volume.

**Implementation**:
- Golden image: seclists already present — no change needed
- Named volume `spectra_wordlists` mounted read-only into sandboxes (`-v spectra_wordlists:/app/wordlists:ro`)
- App container mounts the same volume read-write for uploads
- Remote servers: seclists distributed via registry with the image; custom wordlists synced via rsync/S3 or shared NFS volume

### Q2: How to handle results and wordlists if containers are on another server?

**Decision**: DB-primary for all structured data (already the case) plus S3-compatible object storage for file artifacts, adopted in phases.

**Rationale**: All structured data (stdout/stderr, findings, mission state) already flows through PostgreSQL and works across servers natively. Only file artifacts (`data/missions/{id}/scans/`) need a separate transport. A phased approach avoids premature complexity.

**Implementation**:
- **Phase 1 (single server)**: Keep current shared Docker volume (`spectra_data`). No change.
- **Phase 2 (remote tools)**: NFS mount for `data/missions/` — zero code changes, same filesystem paths.
- **Phase 3 (multi-node)**: Migrate to S3-compatible object storage (MinIO or cloud S3). Standard S3 API allows swapping providers later. - Is there some self hostable docker S3 we can use and auto set up? Remember when adding a server through the UI everything should be auto set up.

### Q3: How to configure VPN in an ephemeral sandbox?

**Decision**: VPN config injected at sandbox creation; first job is `vpn_connect_job` (already implemented).

**Rationale**: `worker.py` already has `vpn_connect_job`/`vpn_disconnect_job` for WireGuard and OpenVPN. Reusing this as the first queued job requires zero new code and reports errors via the normal job mechanism. Each sandbox has its own network namespace, so VPN in one sandbox doesn't affect others.

**Implementation**:
- On `SandboxPool.create_sandbox(mission_id)`: check `mission.vpn_config`; if set, mount config file into sandbox at `/app/vpn_configs/mission.conf:ro`
- First job enqueued is `vpn_connect_job` — worker connects VPN before any tool jobs flow
- Sandbox capabilities already include `NET_ADMIN`, `NET_RAW`, and `/dev/net/tun`

### Q4: How to secure data transfers when containers are on separate servers?

**Decision**: Layered security — PostgreSQL SSL for the data plane, encrypted overlay or WireGuard for the network layer, TLS for file transport.

**Rationale**: The architecture is already secure-by-design because ALL app↔sandbox communication goes through PostgreSQL (job queue + NOTIFY). There are no direct inter-container APIs. Securing PostgreSQL connections secures the entire data plane. File artifacts are the only additional concern.

**Implementation**:
- **Phase 1 (single server)**: Docker bridge network — already isolated. Enforce `sslmode=require` on DATABASE_URL.
- **Phase 2 (remote)**: Docker Swarm overlay with `--opt encrypted` (IPsec) or WireGuard mesh between servers. PostgreSQL `sslmode=verify-full` with client certificates. MinIO/S3 with TLS + pre-signed URLs.
- **Phase 3 (hardened)**: Separate DB user for sandboxes (limited to `job_queue`, `cache_entries` tables). Docker TLS for remote daemon access. mTLS with short-lived certs if direct APIs are added later.

### Q5: How to handle golden image management and distribution?

**Decision**: Automated rebuild on plugin change, with a private Docker registry for multi-server distribution.

**Rationale**: `golden_image.py` parses `plugins/*.json`, generates an ephemeral Dockerfile, and builds `spectra-tools:latest`. Existing sandboxes keep the old image; new sandboxes use the new one. A registry handles image distribution to remote servers.

**Implementation**:
- **Phase 1 (single server)**: Local Docker `registry:2` container — images stay local, layer caching works.
- **Phase 2 (multi-server)**: Harbor (self-hosted with scanning + RBAC) or GHCR (zero infrastructure).
- Build on app server → push to registry → remote nodes pull on sandbox creation.
- Fallback for 1-2 remote servers: `docker save | ssh remote docker load`.

### Q6: What happens when a sandbox goes down mid-mission?

**Decision**: Auto-restart with retry limit (3 attempts) using the existing checkpoint system, then pause and notify the user.

**Rationale**: `Mission.save_checkpoint()` / `Mission.from_checkpoint()` already serialize full mission state (findings, tools_run, task_tree, attack_surface, plan). The `checkpoint_data` column and `resume` flag exist in the DB. Recovery just needs sandbox lifecycle integration.

**Implementation**:
- `SandboxPool` monitors containers via Docker events API (`event=die`) or periodic health checks
- On crash: mark stuck `in_progress` jobs as `failed`, save checkpoint
- Auto-restart: create new sandbox → resume from checkpoint (up to 3 retries)
- After 3 failures: mark mission `paused`, notify user via WebSocket, let them decide
- Add job reaper: periodic task reclaims jobs stuck in `in_progress` longer than `2× timeout`

### Q7: How to handle concurrent missions with limited containers?

**Decision**: Priority queue with per-user limits and a mission status dashboard. No preemption.

**Rationale**: `MAX_CONCURRENT_MISSIONS=3` and `SANDBOX_MAX_CONTAINERS=5` already define capacity limits. `SKIP LOCKED` in the job queue handles atomic claiming. A priority queue with fair scheduling prevents one user from monopolizing slots.

**Implementation**:
- Add `priority` column to `JobQueue`: `ORDER BY priority ASC, enqueued_at ASC`
- Per-user sandbox limit (e.g., max 2 concurrent)
- When at capacity: mission enters `queued` status, dashboard shows queue position
- No preemption — killing running missions is wasteful. Admins can force-stop if needed.

### Q8: What if a tool needs more resources than the sandbox provides?

**Decision**: Static tool-tier resource profiles in plugin JSON, with OOM-based escalation (one retry at next tier).

**Rationale**: Docker does not support increasing memory/CPU limits on a running container. The practical approach is: assign resources based on the heaviest tool the mission needs, detect OOM (exit code 137), recreate with the next tier up. Max one escalation to prevent infinite scaling.

**Implementation**:
- **Tier 1 (light)**: 512MB / 0.5 CPU — nmap, whatweb, subfinder
- **Tier 2 (medium)**: 1GB / 1.0 CPU — gobuster, ffuf, nuclei
- **Tier 3 (heavy)**: 2GB / 2.0 CPU — sqlmap, metasploit, hydra
- **Tier 4 (extreme)**: 4GB / 4.0 CPU — large-scale scans
- New `resources` field in plugin JSON: `{ "tier": "medium", "memory_mb": 1024, "cpu": 1.0 }`
- OOM (exit 137) triggers sandbox recreation at next tier, retry failed job

### Q9: How to handle tool execution timeouts and stuck processes?

**Decision**: Current implementation is already comprehensive. Add a sandbox-level watchdog for defense-in-depth.

**Rationale**: Already has 5 layers: (1) `coreutils timeout` with SIGTERM→SIGKILL escalation, (2) `asyncio.wait_for`, (3) `Job.result(timeout=...)`, (4) per-tool config in plugin JSON with dynamic CIDR scaling, (5) process group kill via `start_new_session`. This covers 99% of cases.

**Implementation**:
- Add sandbox idle watchdog: destroy sandbox if no job completes for `SANDBOX_IDLE_TIMEOUT` seconds
- Add worker heartbeat: periodic timestamp update in DB; `SandboxPool` kills containers with stale heartbeats
- Long-running tools (sqlmap `--crawl`, hydra): plugin JSON `max_timeout` up to 7200s already supported
- Users can cancel via `POST /missions/{id}/cancel`

### Q10: How to handle large tool output transferred back to the app?

**Decision**: Batch transfer (current approach) for the default case, with progress reporting via NOTIFY for UX.

**Rationale**: Most security tool outputs are <10MB — batch capture into DB is simple and reliable. Streaming adds complexity for marginal benefit. The planned LISTEN/NOTIFY upgrade enables progress reporting naturally.

**Implementation**:
- Default: tool stdout/stderr captured in full → stored in `JobQueue.result` → app retrieves when done
- Progress: worker sends periodic `NOTIFY` with status updates (byte count, line count) for long tools
- Large outputs (>10MB): worker redirects to output file (`-o` flag), stores reference in DB; app reads from shared volume or S3
- No gRPC/WebSocket streaming — over-engineering for this use case

### Q11: How to handle the agent accidentally starting interactive mode in a tool?

**Decision**: Already handled — no additional changes needed.

**Rationale**: `stdin` is not connected to tool subprocesses (defaults to `/dev/null`), so tools receive EOF immediately. Most tools detect non-interactive terminal and fall back to defaults or exit. If a tool blocks despite no stdin, the timeout kills it. Process group isolation prevents orphans.

**Implementation**:
- `DEBIAN_FRONTEND=noninteractive` already set in `worker.py`
- Add `TERM=dumb` and `COLUMNS=200` to subprocess env for defense-in-depth
- Enforce non-interactive flags in plugin `args_templates` where available (e.g., sqlmap `--batch`)

### Q12: How to keep the platform secure?

**Decision**: Multi-layer security — network isolation, encrypted transport, least-privilege containers, secrets segregation.

**Rationale**: Defense-in-depth across network, transport, container, and secrets layers. The DB-centric architecture already minimizes the attack surface since there are no direct inter-container APIs.

**Implementation**:
- **Network**: Separate Docker networks (`spectra-data` for app↔db, `spectra-tools` for sandbox↔db). Each sandbox ideally gets its own network.
- **Containers**: Drop all capabilities except `NET_ADMIN`/`NET_RAW`. Read-only root filesystem (`--read-only --tmpfs /tmp`). No Docker socket in sandboxes. PID limit (`--pids-limit 256`). Default seccomp profile.
- **Secrets**: Sandboxes only receive `DATABASE_URL` (limited-privilege user) and `IS_TOOLS_CONTAINER=true`. Never pass `JWT_SECRET_KEY` or `LLM_API_KEY` to sandboxes. Use Docker secrets or tmpfs-mounted files.
- **Audit**: Log all sandbox lifecycle events (create/destroy/crash, VPN, tool exec, resource limit hits).

### Q13: Anything else we missed?

Covered in the Additional Considerations section below.

## Additional Considerations

### DNS / Network Isolation Between Sandboxes

Sandboxes on the same Docker network can resolve each other by name, allowing a malicious tool in sandbox A to target sandbox B. Each sandbox should get its own Docker network (`spectra-sandbox-{mission_id}`), connected to `spectra-network` only for DB access. Use `--dns` to set per-sandbox DNS servers. For strictest isolation, use `--network=none` with VPN-only connectivity.

### Container Image Scanning

The golden image is Kali-based with many tools that may have known CVEs. Scan the image with Trivy or Grype on each rebuild. Block deployment if critical CVEs are found in OS packages or Python dependencies. Accept that security tools (metasploit, etc.) may flag as "vulnerable" by design — focus scanning on the supply chain, not the tools themselves.

### Per-Sandbox Logging / Observability

Ephemeral containers lose their logs on destruction. At minimum, write structured logs to the mission log in the DB (already partially done). For production: use a Docker logging driver (`json-file` with `max-size`) or centralized aggregation (Loki + Promtail). Key metrics per sandbox: CPU/memory usage, tool execution count and duration, network I/O. Export to Prometheus/Grafana for dashboards.

### Mission-Scoped Secrets Management

Some tools need external API keys (Nuclei templates, Shodan/Censys for OSINT). Allow users to upload per-mission secrets, passed to sandboxes as Docker secrets or tmpfs-mounted files. Never persist on the sandbox filesystem, never log or include in job results. Revoke/delete when the mission ends.

### Filesystem Quotas

A tool could write excessive data (recursive download, large scan output). Mitigate with: `--tmpfs /tmp:size=2G` for temp space, `--storage-opt size=10G` where supported, and disk usage monitoring via Docker API. Alert or kill the sandbox if a threshold is exceeded.

### Sandbox Startup Time Optimization (Pre-Warming)

Container cold start takes 1-5s; first image pull can take 30-60s. Pre-warm a pool of idle sandbox containers (`SANDBOX_WARM_POOL=2`). When a mission requests a sandbox, assign a pre-warmed one and spin up a replacement in the background. Ensure `spectra-tools:latest` is pre-pulled on all servers.

### Graceful Cancellation

On user-initiated mission cancel, `SandboxPool` sends SIGTERM to the sandbox container. The worker catches SIGTERM, marks the current job as cancelled, saves checkpoint, and exits gracefully. The container gets a 10s grace period before SIGKILL. This is partially handled by the worker's `CancelledError` handler in `queue.py`.

### Auto Scaling

Admin should be able to add more servers for tools, db, storage (when we add S3), etc.
When added everything needed for the server type selected is auto installed and set up. For example if it's a tools server the golden image is pulled and a few sandboxes are pre warmed. If it's a db server it joins the cluster and starts accepting connections. If it's a storage server it joins the cluster and starts accepting file uploads. - Applies to any service we might need to scale. -- We can also expose admin API endpoints to use for future auto scaling.

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
