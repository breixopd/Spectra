# Spectra Backend API & Database Audit Report

**Date**: 2026-04-27
**Auditor**: Automated Codebase Analysis

---

## 1. File Structure & Module Organisation

### Overall Structure
```
app/
├── api/
│   ├── routers/          # 54 router files organized by domain
│   │   ├── missions/     # lifecycle, catalog, core
│   │   ├── admin/        # user/plan/server management
│   │   ├── auth/         # login, token, setup
│   │   ├── system/       # health, status, operations
│   │   └── findings/, billing/, targets/, tools/, etc.
│   ├── schemas/          # Pydantic request/response models
│   └── dependencies.py   # FastAPI dependency injection
├── core/                 # 26 core modules
│   ├── config.py         # Pydantic Settings
│   ├── database.py      # SQLAlchemy async setup
│   ├── rbac.py           # Role-Based Access Control
│   ├── security.py       # JWT, password hashing, token blacklist
│   ├── exceptions.py     # Custom exception hierarchy
│   ├── rate_limit.py     # Rate limiting
│   ├── middleware.py     # Custom middleware
│   └── ...
├── models/               # SQLAlchemy ORM models
├── repositories/         # 14 repository classes (DAO pattern)
│   ├── base.py           # Generic BaseRepository
│   ├── mission.py, user.py, finding.py, plan.py, etc.
├── services/             # 100+ service files in domain-organized subdirs
│   ├── mission/         # Mission orchestration
│   ├── tools/            # Tool registry, execution, sandbox
│   ├── billing/          # Billing, entitlements, quota
│   ├── ai/               # AI agents, consensus, RAG
│   ├── scaling/          # Docker pool, auto-scaling
│   └── ...
├── utils/                # Utilities (html_sanitization, url_validation, geoip)
├── templates/            # Jinja2 HTML templates
├── worker/               # Worker jobs (tool_jobs, command_jobs, vpn_jobs)
├── main.py               # FastAPI app factory (494 lines)
└── services/ai/__main__.py, services/scheduler/__main__.py, worker/__main__.py
```

**GOOD:**
- Clean separation: `api/`, `core/`, `models/`, `repositories/`, `services/`, `utils/`
- Router split into subdirectories by domain (missions, auth, admin, system)
- Services organized by domain subdirectories
- Repository pattern implemented with `BaseRepository`
- 26 plugins defined as JSON config files

**ISSUES:**
- `main.py` is 494 lines and includes significant routing logic inline rather than in submodules
- `app/__init__.py` is minimal (935 bytes), no clear package exports
- Some services are very large (e.g., `scheduler_service.py` at 40KB)
- ~~Service entry points (`ai_service.py`, `scheduler_service.py`, `worker_service.py`) are root-level files in `app/` rather than within their respective service modules~~ ✅ **RESOLVED**

---

## 2. Separation of Concerns

### Architecture Layers
1. **API Layer** (`app/api/routers/`): Route handlers, HTTP concerns
2. **Service Layer** (`app/services/`): Business logic orchestration
3. **Repository Layer** (`app/repositories/`): Data access abstraction
4. **Model Layer** (`app/models/`): SQLAlchemy ORM models

**GOOD:**
- Routes delegate to services (e.g., `mission_manager` in `core.py`)
- Business logic NOT embedded in route handlers
- Repository pattern centralizes data access
- Mission lifecycle managed by `MissionLifecycleManager` service
- Tool execution through `ToolExecutionService`

**CONCERNS:**
- **`app/api/routers/missions/mission_lifecycle.py` lines 96-99**: After `mission_manager.stop_mission()`, the handler checks resource owner on `active` from `mission_manager.get_mission()` but NOT on `repo.get_by_id()`. The mission could exist in DB but not in memory, potentially bypassing ownership check.
- **`app/api/routers/missions/core.py` lines 286-290**: Getting mission from `mission_manager` first, then DB — ownership check happens only on the in-memory object. If the in-memory state is stale or the mission was never loaded into memory, authorization could fail silently.

**REFACTORING NEEDED:** Ownership check should query DB directly to ensure consistent authorization regardless of in-memory state.

---

## 3. API Design

### REST Principles
**GOOD:**
- Versioned endpoints: `/api/v1/` prefix
- Proper HTTP methods: GET for read, POST for create, DELETE for delete
- Consistent response models via Pydantic schemas
- `PaginatedResponse` for list endpoints
- `StatusResponse` for action endpoints

**ISSUES:**
- Non-versioned routes exist alongside v1 (`/api/admin/`, `/api/auth/`)
- Inconsistent error response shapes across routers
- `/api/v1/missions/` endpoints use `MANAGE_MISSIONS` permission inconsistently:
  - `start_mission`: `require_permission(Permission.MANAGE_MISSIONS)` (line 58)
  - `stop_mission`: `require_permission(Permission.MANAGE_MISSIONS)` (line 91)
  - `pause_mission`: `Depends(get_current_active_user)` — NO permission required (line 125)
  - `resume_mission`: `Depends(get_current_active_user)` — NO permission required (line 159)

### Schema Validation
**GOOD:**
- Pydantic models for all request/response bodies
- Field validators in `StartMissionRequest`:
  - Target stripped of control characters
  - Directive sanitized for prompt injection
  - VPN config pattern: `^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$`

**ISSUES:**
- `mission_catalog.py` `/attack-summary` route returns raw `dict` without schema validation (line 137-154)
- `get_adversary_playbooks` returns raw `dict` without response model

---

## 4. Authentication & Authorization

### JWT Implementation (`app/core/security.py`)
**GOOD:**
- Token types: access, refresh, password_reset, email_verify, unsubscribe
- Bcrypt password hashing with 12 rounds (line 489)
- Token blacklist with DB persistence and PostgreSQL NOTIFY for cross-replica sync
- `invalidated_before` timestamp for user-level token invalidation
- MFA support with TOTP (pyotp)
- BYOK API key encryption with Fernet

**POTENTIAL ISSUES:**
- `_ensure_blacklist_loaded()` has 10-second timeout (line 76-78); if DB is slow during startup, blacklist loads with empty state, potentially accepting revoked tokens momentarily
- In-memory blacklist capped at `JWT_BLACKLIST_MAX_SIZE` (line 200); eviction could theoretically allow a blacklisted token if max size exceeded and expired entries not yet evicted
- `_notify_blacklist_change()` catches `RuntimeError` silently (line 555-556) if no event loop exists

### RBAC (`app/core/rbac.py`)
**GOOD:**
- Permission enum with 16 granular permissions
- Role-to-permission mapping
    - Aliases: `operator` → `staff`
- `require_permission()` FastAPI dependency

### Authorization Gaps
**CRITICAL — `mission_lifecycle.py`:**
- `pause_mission` (line 121-145) and `resume_mission` (line 148-179) use `Depends(get_current_active_user)` instead of `require_permission(Permission.MANAGE_MISSIONS)`
- This allows ANY authenticated user to pause/resume ANY mission if they know the mission ID
- Even though `check_resource_owner` is called, the permission check is missing — a user who is NOT the owner but has an active session could hit these endpoints

**MINOR — `mission_catalog.py` line 120-134:**
- `create_exploit_chain` allows any `get_current_active_user` to create chains; no `MANAGE_TOOLS` permission required

### Ownership Checks
**GOOD:** `check_resource_owner()` in `dependencies.py` handles both dict and object resources, bypasses for superusers.

**ISSUE:** Superuser bypass in `check_resource_owner` (line 195) means any superuser can access any resource without logging. Consider whether this should still be audited.

---

## 5. Database & Migrations

### SQLAlchemy Setup (`app/core/database.py`)
**GOOD:**
- Async SQLAlchemy with `asyncpg`
- Connection pooling: `pool_size=20`, `max_overflow=10`, `pool_timeout=30`
- `pool_recycle=300` prevents stale connections
- `pool_pre_ping=True` tests connections before use
- Disconnect handling: `invalidate_pool_on_disconnect = True`
- Advisory lock support via `advisory_lock_connection()`
- SSL mode handling for PostgreSQL

### Migration Strategy (Alembic)
- 40+ migration files in `alembic/versions/`
- Migration IDs use timestamp-like format
- Some merge migrations exist
- Constraint checks added: `ck_missions_feedback_rating_range`
- Indexes created: `ix_missions_user_id_status`

### N+1 Query Risks
**FOUND:** `mission_catalog.py` lines 60-79:
```python
for m in db_missions:
    counts = get_mission_finding_counts(m)  # N+1 if this makes DB calls
```
This loop could trigger N queries if `get_mission_finding_counts()` accesses relationships lazily. No eager loading seen in the query.

**FOUND:** `core.py` list_missions (lines 229-240) - MissionResponse constructed per row without eager loading relationships.

### Index Coverage
**GOOD:**
- `user_id` indexed on `missions` (`index=True`)
- `status` indexed on `missions`
- `target` indexed on `missions`
- Composite index `ix_missions_user_id_status`
- Check constraints exist

**MISSING:**
- No index on `Mission.created_at` for date-range queries (used in `date_from`/`date_to` filters in `core.py`)
- `Mission.directive` has no index but is used in `search` filter with `contains()`

---

## 6. Plugin System

### Plugin Loading
- Plugins stored as JSON files in `plugins/` directory
- 26 pre-defined plugins (nmap, nuclei, sqlmap, metasploit, etc.)
- `ToolRegistry` class manages loading, validation, installation

### Plugin Upload (`app/api/routers/tools.py`)
**GOOD:**
- `/tools/upload` validates plugin schema before accepting

### Command Execution Sandboxing
**HIGH RISK — `app/services/tools/registry/executor.py`:**
```python
# Line 77: Uses create_subprocess_shell with user-provided commands
proc = await asyncio.create_subprocess_shell(
    prepared_command,  # User input goes here
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    start_new_session=True,
    env=env,
)
```

**MITIGATIONS:**
- Blocklist of dangerous patterns in `app/services/tools/registry/constants.py`:
  - `python -c`, `perl -e`, `ruby -e`, `node -e`, `bash -c`, `sh -c`
  - File overwrites: `>`, `>>`, `|`
  - Background: `&`, `nohup`
- Execution happens in **tools container only** (line 3-6 comment)
- Environment isolation with custom PATH
- Output size limit: `MAX_OUTPUT_SIZE = 1MB`
- Command preparation adds `sudo -n` for root commands (line 45)
- `start_new_session=True` isolates process group for cleanup

**RISKS:**
- Blocklist bypass possible with allowed utilities (e.g., `awk`, `sed`, `cut`)
- No full process isolation (chroot, seccomp, AppArmor)
- No resource limits (CPU time, memory) on subprocess execution
- Blocklist-based filtering is inherently bypassable

### Plugin Schema Validation
**GOOD:** `ToolConfig` Pydantic model validates plugin structure.

**RECOMMENDATION:** Add `-o` output file overwrite check in blocklist since many tools use `-o` for output.

---

## 7. Security

### SQL Injection
**GOOD:** All queries use SQLAlchemy ORM or parameterized `text()` queries. No raw SQL string interpolation seen in routes.

**POTENTIAL ISSUE:** `app/services/compliance/mission_abuse.py` — not reviewed but likely uses user input in evaluation.

### XSS
**GOOD:** HTML templates use Jinja2 auto-escaping. User input in logs/mission directives is stripped of control characters in `mission.py` validators.

**CONCERN:** `mission_catalog.py` `get_attack_summary` returns data directly from memory with no sanitization.

### CSRF
- Not explicitly reviewed; FastAPI doesn't have built-in CSRF protection
- Cookie-based auth used; consider if Double Submit Cookie pattern is implemented

### Path Traversal
**GOOD:** `args_template` uses `{placeholder}` syntax, not direct string interpolation.
- `artifact_workspace.py` uses regex `_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")` to sanitize filenames

### SSRF
- `app/utils/url_validation.py` performs DNS resolution to validate targets
- `app/services/tools/scope_validator.py` validates targets against scope

### Input Validation
**GOOD:**
- Pydantic `field_validator` on mission schemas
- UUID validation for path parameters via `validate_uuid_param()`
- Regex validation on VPN config names

**CONCERN:** `args_template` in tool configs accepts `{placeholder}` that could be filled with unsanitized user input. See `app/api/routers/tools.py` line 514:
```python
placeholders = re.findall(r"\{(\w+)\}", config.execution.args_template)
```

### Secrets Management
**GOOD:** `config.py` supports `_FILE` suffix for Docker Swarm secrets:
```python
JWT_SECRET_KEY_FILE → JWT_SECRET_KEY
SECRET_KEY_FILE → SECRET_KEY
DATABASE_URL_FILE → DATABASE_URL
# etc.
```

**GOOD:** Encryption key auto-generated and persisted to `/app/data/.encryption_key` with `0o600` permissions.

**CONCERN:** `.env.example` and `.env.test` exist but `.env` is in `.gitignore` — good. However, default JWT secret `SecretStr("")` could result in empty string if not set properly.

---

## 8. Error Handling & Logging

### Exception Hierarchy (`app/core/exceptions.py`)
**EXCELLENT:**
- `SpectraError` base with `message`, `code`, `details`
- Specific subclasses: `LLMError`, `ToolError`, `MissionError`, `PluginError`, `AuthError`, `ServiceError`, `ValidationError`
- Status code mapping via `EXCEPTION_STATUS_MAP`

### Error Responses
**GOOD:**
- `main.py` has custom exception handler for `SpectraError` (lines 122-142)
- Returns HTML for browser clients, JSON for API clients
- 5xx errors hide internal details, expose user-friendly messages
- Custom error templates exist

**CONCERN:** Error handler at line 134 shows `exc.message` for client errors (< 500) but default message for server errors. This could leak sensitive info if `exc.message` contains internal details.

### Logging
**GOOD:**
- Structured logging configured via `logging_config.py`
- Correlation ID middleware for request tracing
- Log sanitization: passwords/tokens redacted (line 83-88 of `logging_config.py`)
- Request logging with duration
- Audit logging via `app.services.system.audit.log_event`

**CONCERN:** `mission_lifecycle.py` lines 149-160 catch and log errors silently without re-raising, potentially masking VPN/sandbox cleanup failures:
```python
except (ImportError, OSError, RuntimeError) as e:
    logger.error("Failed to destroy sandbox for mission %s: %s", mission_id, e)
```

---

## 9. Configuration Management

### Settings (`app/core/config.py`)
**GOOD:**
- Pydantic `BaseSettings` with environment variable support
- Validators on all critical settings (timeouts, ports, pool sizes)
- Service-mode-aware pool sizing (lines 85-98):
  - scheduler: pool=8, overflow=8
  - worker: pool=5, overflow=5
  - ai: pool=10, overflow=5
  - api (default): pool=20, overflow=10

**GOOD:** Environment-specific overrides:
- Production auto-detection raises errors for missing required secrets
- DEBUG mode allows defaults for development

**ISSUES:**
- `APP_ENV` default is `"development"` (line 55) — could expose dev defaults in production if not overridden
- `SERVICE_MODE` default `"api"` (line 252) — good, but ambiguous when empty string is also valid ("all" behavior when empty)

### Environment Files
- `.env.example` — template
- `.env.test` — test configuration
- No `.env` in git (correctly gitignored)
- `.env.test.example` exists

---

## 10. Performance

### Synchronous I/O in Async Contexts
**FOUND:** `app/utils/url_validation.py` line 24:
```python
addr_info = await loop.run_in_executor(None, socket.getaddrinfo, hostname, None)
```
This is correct — wrapped with `run_in_executor`. No blocking I/O found in async handlers.

**FOUND:** `app/services/billing/payment_adapter.py` lines 137-211:
```python
customer = await loop.run_in_executor(None, lambda: self._stripe.Customer.retrieve(customer_id))
```
Synchronous Stripe SDK calls are wrapped in executor. Good.

### Heavy Computations in Request Handlers
**FOUND:** `mission_catalog.py` `get_missions_summary` (lines 35-81):
```python
for m in db_missions:
    counts = get_mission_finding_counts(m)  # Called per mission
```
For 100 missions, this could be 100 separate queries.

**FOUND:** `core.py` `list_missions` (lines 229-240):
```python
items = [
    MissionResponse(
        ...
        findings=get_mission_output_findings(m),  # Per-row processing
    )
    for m in missions
]
```

### Connection Pool Sizing
- Default pool 20 with overflow 10 = max 30 connections per API instance
- Redis connection via `aioredis` (assumed from `rate_limit.py`)
- If running multiple API replicas, each has independent pool

### Caching
- Redis used for rate limit storage
- Tool status cached in Redis
- No in-memory caching layer seen (application-level)

---

## Critical Findings Summary

### 🔴 HIGH Severity

1. **`mission_lifecycle.py` missing RBAC on pause/resume** (lines 125, 159): Uses `get_current_active_user` instead of `require_permission(Permission.MANAGE_MISSIONS)`. Any authenticated user can pause/resume any mission.

2. **`mission_lifecycle.py` inconsistent ownership check** (lines 96-99): Ownership verification only on in-memory mission object. If mission not in memory, check is skipped.

3. **Subprocess shell execution in tools container** (`executor.py` line 77): Uses `create_subprocess_shell` with user-controlled command strings despite blocklist. Blocklist bypass possible via allowed utilities.

4. **Missing database index on `Mission.created_at`**: Date-range queries on missions will do full table scans.

### 🟡 MEDIUM Severity

5. **N+1 query in `get_missions_summary`** (`mission_catalog.py` lines 60-79): Loop calls `get_mission_finding_counts(m)` per mission.

6. **Error message leakage potential** (`main.py` line 134): `exc.message` returned for non-5xx errors.

7. **Blacklist load timeout** (`security.py` line 76-78): 10-second wait could block requests if DB slow.

8. ~~`PLUGIN_SAFE_MODE` can be disabled~~: Plugin signing feature removed.

9. **No rate limiting on internal `/internal/metrics` endpoint** (line 321-331): Requires `X-Service-Auth` header only; no brute-force protection.

### 🟢 LOW / Informational

10. **`app_env` defaults to `"development"`**: Production deployments must explicitly set this.

11. **Superuser bypass in ownership checks**: Admins can access any resource without audit trail.

12. **TODO/FIXME search returned no results**: Good — no obvious incomplete code markers.

13. **No test files executed during audit**: Tests exist but not run.

---

## Recommended Refactorings

### 1. Fix Authorization Gap (Critical)
```python
# mission_lifecycle.py - pause_mission and resume_mission
# Change from:
_current_user: User = Depends(get_current_active_user),
# To:
_current_user: User = require_permission(Permission.MANAGE_MISSIONS),
```

### 2. Consistent Ownership Check
```python
# mission_lifecycle.py - stop_mission
# Query DB for mission ownership even if not in memory:
mission = await repo.get_by_id(mission_id)
if not mission:
    raise HTTPException(status_code=404, detail="Mission not found")
check_resource_owner(mission, _current_user, "mission")
```

### 3. Add Missing Database Index
```sql
-- Migration: add index on missions.created_at for date-range queries
CREATE INDEX ix_missions_created_at ON missions(created_at DESC);
```

### 4. Eager Loading for Mission Lists
```python
# core.py list_missions - use selectinload for relationships
from sqlalchemy.orm import selectinload
stmt = select(Mission).options(
    selectinload(Mission.findings),
    selectinload(Mission.targets)
)
```

### 5. Blocklist Enhancement for Plugin Execution
Add output file overwrite pattern to blocklist:
```python
r"-o\s+",  # nmap -oX, ffuf -o, etc.
r"--output",
```
