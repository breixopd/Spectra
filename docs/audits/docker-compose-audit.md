# Spectra Docker & Docker Compose Infrastructure Audit Report

**Date**: 2026-04-27
**Auditor**: Automated Codebase Analysis
**Scope**: `docker/`, `.dockerignore`, all Dockerfiles, compose files, Caddyfiles, `garage.toml`
**Files Audited**: 21 files (8 Dockerfiles, 4 compose files, 4 Caddyfiles, 2 init scripts, 1 garage.toml, 1 `.dockerignore`, 1 `.dockerignore` override)

---

## Executive Summary

The Spectra platform uses a well-structured multi-service Docker setup with strong security defaults (`cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, `read_only` on API containers, tmpfs mounts, and healthchecks). However, **the production `docker-compose.yml` contains multiple bind mounts and development-oriented features that violate the principle of self-contained production images**. Additionally, a **critical runtime bug** exists in `Dockerfile.scheduler` where required application modules are missing from the image, which will cause `ModuleNotFoundError` on startup.

| Area | Status | Score | Key Issue |
|------|--------|-------|-----------|
| **Image Reproducibility** | 🔴 Critical | 4/10 | `latest` tags on TensorZero, Kali Linux; no digest pinning |
| **Production Compose** | 🔴 Critical | 3/10 | Bind mounts, `build:` sections, `develop:` watch, Docker socket exposure |
| **Runtime Correctness** | 🔴 Critical | 2/10 | `Dockerfile.scheduler` missing `app/telemetry/` (runtime crash) |
| **Secret Management** | 🟡 Medium | 6/10 | `.env` loaded as `env_file`, Redis fallback password, env var secrets in compose |
| **Image Hardening** | 🟡 Medium | 6/10 | Missing `USER` in API/AI/Scheduler images; Grype bloat in API; no `PYTHONDONTWRITEBYTECODE` |
| **Worker Security** | 🔴 Critical | 4/10 | Writable rootfs (`read_only: false`), no `tmpfs`, `NET_ADMIN`/`NET_RAW` capabilities |
| **.dockerignore** | 🟡 Medium | 5/10 | Missing exclusions for ops scripts, docker configs, build artifacts |
| **Caddy / Edge Proxy** | 🟢 Strong | 8/10 | Good security headers, HSTS, rate limiting; missing CSP |
| **Swarm Compose** | 🟢 Strong | 8/10 | No bind mounts, uses secrets/configs, encrypted overlay networks |
| **Layer Caching** | 🟡 Medium | 6/10 | `apt-get update` duplication, `chmod` in separate layer, no `npm ci` |

---

## 1. CRITICAL Findings

### 1.1 `Dockerfile.scheduler` Missing Required `app/telemetry/` Module

**File**: `docker/Dockerfile.scheduler`  
**Lines**: 54–68  
**Risk**: Runtime crash (`ModuleNotFoundError`) on scheduler startup or during task execution.

`app/services/scheduler/__main__.py` lazily imports `app.infrastructure.metrics_store` (line 170) and `app.services.billing.usage_tracker` (line 150). Both of these modules import `app.telemetry.telemetry`. The scheduler Dockerfile copies `app/infrastructure/` and `app/services/` but **does not copy `app/telemetry/`**.

**Impact**: The scheduler service will crash when it attempts to collect metrics or reset quotas.

**Fix**:
```dockerfile
# Add to docker/Dockerfile.scheduler after line 60 (app/infrastructure/)
COPY --chown=spectra:spectra app/telemetry/ ./app/telemetry/
```

Additionally, `Dockerfile.scheduler` is also missing `app/mission/` (present in `Dockerfile.ai` and `Dockerfile.worker`). While `app/models/` uses lazy `__getattr__` loading and `ServerNode` does not transitively import `app.mission`, other scheduler code paths (e.g., `app.services.scaling` or `app.services.tools`) may reach `app.mission.core.enums`. Copy `app/mission/` as a defensive measure:
```dockerfile
COPY --chown=spectra:spectra app/mission/ ./app/mission/
```

---

### 1.2 Production `docker-compose.yml` Contains Bind Mounts

**File**: `docker/docker-compose.yml`  
**Risk**: Self-contained production images are violated; host filesystem coupling prevents immutable deployments.

The following bind mounts are present in the file labeled "local development stack" but used as the production compose:

| Line | Bind Mount | Issue |
|------|-----------|-------|
| 44 | `./garage.toml:/etc/garage.toml:ro` | Host config file mounted into Garage |
| 131 | `./Caddyfile.snippets:/etc/caddy/Caddyfile.snippets:ro` | Host Caddy snippets mounted |
| 132 | `./Caddyfile.prod:/etc/caddy/Caddyfile:ro` | Host Caddyfile mounted |
| 316 | `../config/tensorzero.toml:/app/config/tensorzero.toml:ro` | Host TensorZero config mounted |

**Fix**: Remove all bind mounts. Embed configs into images or use Docker Swarm `configs:` (as done in `docker-compose.swarm.yml`). For compose-only production, bake `garage.toml`, `Caddyfile.prod`, `Caddyfile.snippets`, and `tensorzero.toml` into their respective images via `COPY` in Dockerfiles, or use named volumes populated by an init container.

---

### 1.3 `docker-compose.yml` Contains `build:` Sections and `develop:` Watch

**File**: `docker/docker-compose.yml`  
**Lines**: 119–122 (caddy), 157–161 (app), 215–222 (`develop:`), 226–228 (ai-svc), 339–343 (scheduler), 383–388 (worker)

`build:` sections in a production compose file allow accidental local image builds, bypassing CI/CD artifact promotion. The `develop:` watch block (lines 215–222) is a Docker Compose development feature that syncs host `../app` into the container. This has no place in production.

**Fix**: Remove all `build:` and `develop:` blocks from `docker-compose.yml`. The production file should reference pre-built images (e.g., `${REGISTRY:-ghcr.io/breixopd14/}spectra-app:${VERSION}`) and rely on `docker-compose.swarm.yml` for orchestration.

---

### 1.4 Docker Socket Bind Mount in Scheduler (Production Compose)

**File**: `docker/docker-compose.yml`  
**Line**: 361  
**Risk**: Full host compromise if scheduler container is breached.

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

Even with `:ro`, the Docker socket grants full container lifecycle control over the host. The scheduler uses this for Docker cleanup tasks. In a production environment, this should be replaced with a Docker API proxy (e.g., `tecnativa/docker-socket-proxy`) with restricted permissions, or the scheduler should run on a dedicated manager node with strict network policies.

**Fix**: Replace direct socket mount with a restricted Docker socket proxy, or document that the scheduler **must** run on an isolated manager node with no user-facing services.

---

### 1.5 Worker Service Runs with Writable Root Filesystem

**File**: `docker/docker-compose.yml`  
**Lines**: 383–429  
**Risk**: Worker executes untrusted plugin code and network-facing tools; writable rootfs increases persistence risk.

The `worker` service:
- Does **not** have `read_only: true`
- Does **not** have `tmpfs` mounts
- Has `cap_add: [NET_ADMIN, NET_RAW]` (required for nmap/WireGuard)
- Handles untrusted plugin output

This is the highest-risk service in the stack and should have the most restrictive filesystem possible.

**Fix**:
```yaml
worker:
  read_only: true
  tmpfs:
    - /tmp
    - /var/tmp
    - /app/logs
  volumes:
    - spectra_data:/app/data
    - spectra_plugins:/app/plugins
    - spectra_tools_data:/opt/spectra_tools
```

Ensure the worker Dockerfile creates writable directories for `/app/logs`, `/tmp`, and tool installation paths before marking the image read-only.

---

### 1.6 Hardcoded Fallback Password for Redis

**File**: `docker/docker-compose.yml`  
**Line**: 98  
**Risk**: Predictable default credential if `.env` is incomplete.

```yaml
command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD:-change-me-redis-pass}"]
```

If `REDIS_PASSWORD` is unset, Redis starts with the publicly known password `change-me-redis-pass`. The healthcheck (line 102) also embeds this fallback.

**Fix**: Remove the fallback. Use shell interpolation that fails fast:
```yaml
command: ["sh", "-c", 'redis-server --appendonly yes --requirepass "$${REDIS_PASSWORD:?REDIS_PASSWORD must be set}"']
```

---

### 1.7 `latest` Tag on External Images

**File**: `docker/docker-compose.yml` (line 305), `docker/docker-compose.swarm.yml` (line 541)  
**Risk**: Non-reproducible builds, supply chain attacks via unexpected image updates.

```yaml
image: ${TENSORZERO_IMAGE:-tensorzero/gateway:latest}
```

**Fix**: Pin to a specific digest or minor version tag:
```yaml
image: tensorzero/gateway:v2025.01.0@sha256:abc123...
```

---

## 2. HIGH Findings

### 2.1 `kalilinux/kali-rolling:latest` in Worker Dockerfile

**File**: `docker/Dockerfile.worker`  
**Line**: 15  
**Risk**: Rolling distro + `latest` tag = unpredictable, non-reproducible builds.

The Dockerfile comment acknowledges this risk and suggests pinning to a digest, but the actual `ARG` uses `latest`.

**Fix**: Pin to a specific digest in production:
```dockerfile
ARG KALI_BASE_IMAGE=kalilinux/kali-rolling@sha256:...
```

---

### 2.2 Docker Socket Bind Mount in Swarm Scheduler

**File**: `docker/docker-compose.swarm.yml`  
**Lines**: 302–305  
**Risk**: Same as 1.4 — full host compromise.

**Fix**: Same as 1.4.

---

### 2.3 Worker Lacks `read_only` and `tmpfs` in Swarm

**File**: `docker/docker-compose.swarm.yml`  
**Lines**: 342–393  
**Risk**: Same as 1.5 — writable rootfs on highest-risk service.

**Fix**: Same as 1.5.

---

### 2.4 Grype Installed in API Runtime Image

**File**: `docker/Dockerfile.api`  
**Lines**: 58–75  
**Risk**: Image bloat (~50MB+) and expanded attack surface. Grype is a CLI vulnerability scanner; it has no role in a production API runtime.

**Fix**: Remove Grype from the runtime stage. Run image scanning in CI/CD (e.g., Trivy, Snyk) instead. If runtime scanning is required, use a separate sidecar or init container.

---

### 2.5 `.env` Loaded as `env_file` in Production Compose

**File**: `docker/docker-compose.yml`  
**Lines**: 179, 241, 354, 399  
**Risk**: Entire `.env` file (containing all secrets, comments, and extraneous variables) is injected into container environments. This increases blast radius if any single service is compromised.

**Fix**: Remove `env_file:` declarations. Pass only required variables explicitly via `environment:` or use Docker secrets (even in compose, via file-based secrets). At minimum, split secrets into a dedicated `.env.secrets` file with restricted permissions.

---

### 2.6 `--forwarded-allow-ips "*"` in API Dockerfile

**File**: `docker/Dockerfile.api`  
**Line**: 106  
**Risk**: Uvicorn trusts `X-Forwarded-For` from any IP address. In a containerized environment behind Caddy, this should be restricted to the internal Docker network or the Caddy container IP.

**Fix**: Restrict to RFC 1918 private networks:
```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
```

---

### 2.7 Missing `USER` Directive in API, AI, and Scheduler Dockerfiles

**File**: `docker/Dockerfile.api`, `docker/Dockerfile.ai`, `docker/Dockerfile.scheduler`  
**Lines**: EOF (no `USER spectra`)  
**Risk**: If the `ENTRYPOINT` is overridden (e.g., `docker run --entrypoint /bin/sh`), the container starts as `root`. Defense in depth demands explicit `USER`.

**Fix**: Add `USER spectra` before `ENTRYPOINT` in all three Dockerfiles. Ensure `start.sh` does not rely on being root (it already uses `gosu`, so this is a safe change).

---

### 2.8 Missing `PYTHONDONTWRITEBYTECODE=1` with `read_only` Containers

**File**: `docker/Dockerfile.api`, `docker/Dockerfile.ai`, `docker/Dockerfile.scheduler`  
**Risk**: Python attempts to write `__pycache__` directories next to source files. With `read_only: true` in compose, this causes `EROFS` errors or forces Python to run in bytecode-less mode with degraded performance.

**Fix**: Add to all Python Dockerfiles:
```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
```

---

### 2.9 ClickHouse Missing Required Capabilities in Compose

**File**: `docker/docker-compose.yml`  
**Lines**: 271–301  
**Risk**: ClickHouse container entrypoint may fail to `chown` data directories because `security-stateful` only grants `SETUID`/`SETGID`. In `docker-compose.swarm.yml`, ClickHouse has `CHOWN`, `FOWNER`, `DAC_OVERRIDE`, and `SYS_NICE`.

**Fix**: In `docker-compose.yml`, override capabilities for ClickHouse:
```yaml
clickhouse:
  cap_drop: [ALL]
  cap_add: [SETUID, SETGID, CHOWN, FOWNER, DAC_OVERRIDE, SYS_NICE]
```

---

## 3. MEDIUM Findings

### 3.1 Entire `scripts/` Directory Copied into Production Images

**File**: `docker/Dockerfile.api` (line 85), `docker/Dockerfile.ai` (line 53), `docker/Dockerfile.scheduler` (line 54)  
**Risk**: `scripts/` contains `deploy.sh`, `rollback.sh`, `health_check.sh`, `live_smoke.py`, `first_run.sh`, and `ops/` subdir — none of which are needed at runtime. Increases image size and attack surface.

**Fix**: Copy only `scripts/start.sh`:
```dockerfile
COPY --chown=spectra:spectra scripts/start.sh ./scripts/
```

---

### 3.2 Build Config Files Copied into API Runtime Image

**File**: `docker/Dockerfile.api`  
**Lines**: 93–94  
**Risk**: `config/tailwind.config.js` and `config/postcss.config.js` are only needed for the builder stage. They are not needed at runtime because CSS is pre-built.

**Fix**: Remove lines 93–94 from `Dockerfile.api`.

---

### 3.3 Layer Caching Inefficiency in API Builder

**File**: `docker/Dockerfile.api`  
**Lines**: 11, 27  
**Risk**: `apt-get update` is executed twice in the builder stage, creating redundant layers and cache invalidation.

**Fix**: Combine system package installs into a single `RUN` layer, or move Node.js installation to a separate stage.

---

### 3.4 Worker Dockerfile Not Multi-Stage

**File**: `docker/Dockerfile.worker`  
**Risk**: Build dependencies (`gcc`, `libpq-dev`, `libffi-dev`, `pkg-config`, `libpcap-dev`, `python3-dev`) remain in the final image, inflating size by hundreds of megabytes.

**Fix**: Convert to a multi-stage build: install build deps and `pip install` in a builder stage, then copy `/opt/venv` to a clean Kali runtime stage.

---

### 3.5 Unnecessary Files Copied into AI and Scheduler Images

**File**: `docker/Dockerfile.ai` (lines 66–68), `docker/Dockerfile.scheduler` (lines 65–67)  
**Risk**: Both services set `SKIP_MIGRATIONS: "true"` in compose, yet they copy `alembic/` and `config/alembic.ini`. The AI service also copies `plugins/` which it likely does not need.

**Fix**: Remove `alembic/`, `config/alembic.ini`, and `plugins/` from `Dockerfile.ai`. Remove `alembic/` and `config/alembic.ini` from `Dockerfile.scheduler` unless they are genuinely required.

---

### 3.6 Missing `Content-Security-Policy` in Production Caddyfile

**File**: `docker/Caddyfile.prod`  
**Risk**: No CSP header means browsers have no instruction to block inline scripts or restrict asset sources, increasing XSS impact.

**Fix**: Add a strict CSP (tailored to Spectra's static asset needs):
```caddyfile
header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self';"
```

---

### 3.7 Redis Password Exposed in Process List via Healthcheck

**File**: `docker/docker-compose.yml`  
**Line**: 102  
**Risk**: `redis-cli -a ${REDIS_PASSWORD} ping` exposes the password in `ps` output inside the container.

**Fix**: Use the `REDISCLI_AUTH` environment variable instead of `-a`:
```yaml
healthcheck:
  test: ["CMD-SHELL", "REDISCLI_AUTH='${REDIS_PASSWORD}' redis-cli ping"]
```

---

### 3.8 TensorZero API Key in Environment Variable (Compose)

**File**: `docker/docker-compose.yml`  
**Line**: 320  
**Risk**: `OPENAI_API_KEY` is passed directly via `environment:`. Visible in `docker inspect` and process environment.

**Fix**: For non-Swarm compose, use a file-based secret mounted as a read-only volume, and have an init script read it (as done in `docker-compose.swarm.yml` with `tensorzero-init.sh`).

---

### 3.9 Swarm TensorZero Env Var Duplicates Secret

**File**: `docker/docker-compose.swarm.yml`  
**Line**: 566  
**Risk**: `OPENAI_API_KEY: ${OPENAI_API_KEY:-}` is set alongside the `openai_api_key` secret. The `tensorzero-init.sh` script correctly prefers the secret file, but the env var is still visible in `docker inspect`.

**Fix**: Remove `OPENAI_API_KEY` from the `environment:` block in `docker-compose.swarm.yml` and rely solely on the secret file + init script.

---

### 3.10 Missing Restart Policies

**File**: `docker/docker-compose.yml`  
**Lines**: 271 (clickhouse), 303 (tensorzero)  
**Risk**: `clickhouse` and `tensorzero` do not have `restart: unless-stopped` or `restart: always`. They will not recover automatically after a host reboot or daemon crash.

**Fix**: Add `restart: unless-stopped` to both services.

---

### 3.11 Missing Resource Reservations

**File**: `docker/docker-compose.yml`  
**Risk**: `ai-svc`, `scheduler`, and `caddy` lack `deploy.resources.reservations`, making scheduling and capacity planning difficult.

**Fix**: Add reservations:
```yaml
ai-svc:
  deploy:
    resources:
      reservations:
        cpus: '0.25'
        memory: 256M
scheduler:
  deploy:
    resources:
      reservations:
        cpus: '0.1'
        memory: 128M
caddy:
  deploy:
    resources:
      reservations:
        cpus: '0.1'
        memory: 64M
```

---

### 3.12 `Dockerfile.test.dockerignore` Is a Dead File

**File**: `docker/Dockerfile.test.dockerignore`  
**Risk**: Docker does not recognize this filename. Only `.dockerignore` in the build context root is used. The file gives a false sense of security.

**Fix**: Delete `docker/Dockerfile.test.dockerignore`. If a separate ignore is needed for `Dockerfile.test`, use BuildKit's `--ignorefile` flag or create a dedicated build context.

---

## 4. LOW Findings

### 4.1 Missing `cpus` Limit for Garage and Caddy

**File**: `docker/docker-compose.yml`  
**Lines**: 56–60 (garage), 147–154 (caddy)  
**Fix**: Add `cpus: '0.25'` to garage and `cpus: '0.5'` to caddy.

---

### 4.2 Missing `stop_grace_period`

**File**: `docker/docker-compose.yml`  
**Lines**: 118 (caddy), 383 (worker)  
**Fix**: Add `stop_grace_period: 30s` to `caddy` and `worker` for graceful shutdown.

---

### 4.3 Redis Image Not Pinned to Minor Version

**File**: `docker/docker-compose.yml`  
**Line**: 93  
**Risk**: `redis:7-alpine` will silently update to Redis 7.3+ when released.

**Fix**: Pin to `redis:7.2-alpine` or a specific digest.

---

### 4.4 `chmod` in Separate Layer

**File**: `docker/Dockerfile.api` (line 95), `docker/Dockerfile.ai` (line 70), `docker/Dockerfile.scheduler` (line 69)  
**Risk**: Extra image layer; does not invalidate cache efficiently.

**Fix**: Use BuildKit `COPY --chmod=+x` (Dockerfile syntax 1.4+):
```dockerfile
COPY --chmod=+x --chown=spectra:spectra scripts/start.sh ./scripts/
```

---

### 4.5 `apt-get upgrade` in Dockerfiles

**File**: `docker/Dockerfile.api` (lines 11, 48), `docker/Dockerfile.ai` (lines 11, 38), `docker/Dockerfile.scheduler` (lines 11, 38)  
**Risk**: Non-reproducible builds; package versions change between builds.

**Fix**: Remove `apt-get upgrade -y`. Keep base images updated via CI/CD image rebuilds instead.

---

### 4.6 `.dockerignore` Missing Common Exclusions

**File**: `.dockerignore`  
**Risk**: Image bloat and potential leakage of development artifacts.

Missing entries:
```gitignore
scripts/ops/
docker/
!docker/Dockerfile.*
Makefile
pyproject.toml
.gitattributes
.editorconfig
.pre-commit-config.yaml
*.log
*.tmp
.DS_Store
Thumbs.db
.aws/
.ssh/
.gnupg/
```

**Fix**: Add the above exclusions. Note: `docker/` should be excluded except for Dockerfiles if they are referenced by downstream builds.

---

### 4.7 `npm install` Instead of `npm ci`

**File**: `docker/Dockerfile.api`  
**Line**: 31  
**Risk**: `npm install` may update packages beyond the lockfile. `npm ci` is deterministic.

**Fix**: Replace `npm install` with `npm ci`.

---

### 4.8 Test Compose Uses `user: root` and `seccomp: unconfined`

**File**: `docker/docker-compose.test.yml`  
**Lines**: 299, 349, 414, 466, 506 (`user: root`); 354 (`seccomp:unconfined`)  
**Risk**: Test-only; acceptable for isolated CI but should be documented.

**Fix**: Add a comment header in `docker-compose.test.yml` warning that these settings are test-only and must not be used in production.

---

## 5. Positive Findings

1. **Swarm compose has no bind mounts** — uses `configs:`, `secrets:`, and named volumes exclusively.
2. **Encrypted overlay networks** — `docker-compose.swarm.yml` sets `driver_opts: encrypted: "true"` on all networks.
3. **Healthchecks on all custom services** — every Python service and infrastructure service has a defined healthcheck.
4. **`cap_drop: [ALL]` as default** — the `x-security` anchor drops all capabilities by default.
5. **`read_only: true` + `tmpfs` on API/AI/Scheduler** — good defense-in-depth for the main application containers.
6. **`no-new-privileges:true`** — prevents privilege escalation attacks.
7. **Garage admin/API ports bound to `127.0.0.1`** — not exposed to all interfaces in compose.
8. **Caddyfile.prod disables admin endpoint** — `admin off` reduces Caddy attack surface.
9. **Private docs hidden** — `/docs`, `/redoc`, `/openapi.json` return 404 in production Caddy config.
10. **Rate limiting in Caddy** — public auth and register endpoints have per-IP rate limits.
11. **HSTS header present** — `Strict-Transport-Security` with `includeSubDomains; preload`.
12. **Specific version tags for most images** — `pgvector:pg16`, `clickhouse-server:24.11-alpine`, `garage:v2.2.0`, `python:3.11.13-slim-bookworm`, `caddy:2.9.1-alpine`.
13. **`start.sh` handles secret resolution** — `_FILE` env vars are resolved for Swarm secrets, and socket permissions are managed safely.
14. **Worker runs as non-root** — `USER spectra` with selective `sudo` for specific tools.

---

## 6. Summary of Recommended Priority Actions

| Priority | Action | File(s) |
|----------|--------|---------|
| **P0** | Add `COPY app/telemetry/` (and `app/mission/`) to `Dockerfile.scheduler` | `docker/Dockerfile.scheduler` |
| **P0** | Remove all bind mounts from `docker-compose.yml` | `docker/docker-compose.yml` |
| **P0** | Remove `build:` and `develop:` sections from `docker-compose.yml` | `docker/docker-compose.yml` |
| **P0** | Add `read_only: true` + `tmpfs` to worker in compose and swarm | `docker/docker-compose.yml`, `docker/docker-compose.swarm.yml` |
| **P0** | Remove Redis fallback password | `docker/docker-compose.yml` |
| **P0** | Pin TensorZero image to digest/version | `docker/docker-compose.yml`, `docker/docker-compose.swarm.yml` |
| **P1** | Pin Kali base image to digest | `docker/Dockerfile.worker` |
| **P1** | Remove Grype from API runtime image | `docker/Dockerfile.api` |
| **P1** | Remove `env_file: ../.env` from all services | `docker/docker-compose.yml` |
| **P1** | Restrict `--forwarded-allow-ips` to private networks | `docker/Dockerfile.api` |
| **P1** | Add `USER spectra` to API, AI, Scheduler Dockerfiles | `docker/Dockerfile.api`, `docker/Dockerfile.ai`, `docker/Dockerfile.scheduler` |
| **P1** | Add `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1` to all Python images | All `Dockerfile.*` |
| **P1** | Fix ClickHouse capabilities in compose | `docker/docker-compose.yml` |
| **P2** | Copy only `scripts/start.sh` into production images | `docker/Dockerfile.api`, `docker/Dockerfile.ai`, `docker/Dockerfile.scheduler` |
| **P2** | Remove build config files from API runtime | `docker/Dockerfile.api` |
| **P2** | Convert worker to multi-stage build | `docker/Dockerfile.worker` |
| **P2** | Add CSP header to Caddyfile.prod | `docker/Caddyfile.prod` |
| **P2** | Fix Redis healthcheck to avoid password in process list | `docker/docker-compose.yml` |
| **P2** | Add restart policies to clickhouse and tensorzero | `docker/docker-compose.yml` |
| **P2** | Expand `.dockerignore` | `.dockerignore` |
| **P3** | Add resource reservations to ai-svc, scheduler, caddy | `docker/docker-compose.yml` |
| **P3** | Delete unused `Dockerfile.test.dockerignore` | `docker/Dockerfile.test.dockerignore` |
| **P3** | Replace `npm install` with `npm ci` | `docker/Dockerfile.api` |

---

*Report generated by automated codebase analysis. All line numbers reference the state of the repository as of the audit date.*
