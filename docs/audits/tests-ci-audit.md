# Spectra Testing Infrastructure Audit Report

**Date**: 2026-04-27
**Auditor**: Automated Codebase Analysis

---

## 1. Test Structure

```
tests/
├── conftest.py              # Root session fixtures (mock_llm, mock_ws, mock_db, reset_singletons, mock_storage)
├── helpers.py               # Shared test utilities
├── platform_harness.py      # Load/soak/performance shared utilities
├── mocks/
│   ├── __init__.py
│   └── llm.py               # MockLLMClient for unit tests
├── unit/                    # ~100+ unit test files
│   ├── api/
│   ├── core/               # core infrastructure (cache, db, rate_limiting, events, telemetry, etc.)
│   ├── services/           # service-layer unit tests
│   ├── worker/             # worker subsystem tests
│   ├── test_*.py           # top-level unit tests
│   └── test_version.py
├── integration/             # 25 integration test files
│   ├── conftest.py         # integration-specific fixtures
│   ├── test_agents_integration.py   # ENTIRELY SKIPPED
│   ├── test_api_health.py
│   ├── test_auth_flow.py
│   ├── test_exploit_db_integration.py
│   ├── test_infrastructure.py
│   ├── test_llm_live.py
│   ├── test_live_scan.py
│   ├── test_live_targets.py
│   ├── test_mission_flow.py
│   ├── test_queue.py
│   ├── test_rag_integration.py
│   ├── test_real_tool_workflow.py
│   ├── test_server_pool_integration.py
│   ├── test_safety.py
│   ├── test_steering.py
│   ├── test_storage_integration.py
│   ├── test_tool_execution.py
│   ├── test_tool_integration.py
│   ├── test_tools_container.py
│   └── test_ops_scripts_live.py
├── e2e/
│   ├── conftest.py         # E2E fixtures (wait_for_mission_status, get_mission_logs)
│   ├── test_api_live.py    # Live API E2E (APP_BASE_URL required)
│   ├── test_full_api_workflow.py  # Full workflow E2E
│   ├── test_live_campaign.py
│   ├── test_plugin_management.py
│   └── ui/
│       ├── conftest.py     # Playwright fixtures
│       ├── harness/
│       │   ├── __init__.py
│       │   ├── navigation.py
│       │   └── db_user.py  # DB user provisioning fixture (skips if DATABASE_URL not set)
│       ├── test_*.py       # ~20 Playwright UI test files
├── load/                    # 7 load/burst test files
│   ├── conftest.py
│   ├── test_password_reset_bursts.py
│   ├── test_rate_limit_bursts.py
│   ├── test_multi_replica_rate_limits.py
│   ├── test_recovery_windows.py
│   ├── test_tool_worker_concurrency.py
│   ├── test_websocket_churn.py
├── performance/
│   ├── conftest.py
│   └── test_api_latency.py  # performance route latency smoke tests
└── soak/
    ├── conftest.py
    └── test_mixed_traffic_stability.py  # mixed-traffic soak harness
```

**Verdict**: Tests are well-organized in logical subdirectories. Unit, integration, E2E (API and Playwright UI), load, performance, and soak test tiers exist. Each tier has its own `conftest.py` with tier-appropriate autouse fixtures.

---

## 2. Skipped Tests — Complete Inventory

Found **38 skip calls across 17 files**. All are **conditional** (not hard-coded permanently disabled), meaning they are triggered by missing infrastructure.

### 2.1 Skips by File

| File | Line | Reason | Fixable? |
|------|------|--------|----------|
| `tests/integration/test_agents_integration.py:5` | `pytestmark = pytest.mark.skip(reason="Mock LLM provider not implemented")` | **Entire test file skipped** — MockLLMClient exists but no mock provider registration | **YES** — Implement mock LLM provider for agent integration tests |
| `tests/integration/test_rag_integration.py:12-15` | `pytest.mark.skipif("sqlite" in DATABASE_URL, ...)` | RAG requires PostgreSQL with pgvector | NO (pgvector required) |
| `tests/integration/test_rag_integration.py:27` | `pytest.skip("RAG local embeddings require optional dependency 'fastembed'")` | fastembed not installed | Install fastembed |
| `tests/integration/test_rag_integration.py:32` | `pytest.skip("RAG initialization failed (PostgreSQL/pgvector not available)")` | pgvector unavailable | Ensure pgvector in test DB |
| `tests/integration/test_queue.py:36` | `pytest.skip("Queue integration tests require a PostgreSQL test DB")` | Not PostgreSQL | Use PostgreSQL test DB |
| `tests/integration/test_queue.py:53` | `pytest.skip("Queue integration tests require a reachable PostgreSQL test DB")` | DB unreachable | Ensure test DB reachable |
| `tests/integration/test_server_pool_integration.py:22` | `pytest.mark.skipif("sqlite" in DATABASE_URL, ...)` | sqlite detected | Use PostgreSQL |
| `tests/integration/test_server_pool_integration.py:65` | `pytest.skip(f"PostgreSQL not reachable: {e}")` | DB connection failed | Ensure PostgreSQL reachable |
| `tests/integration/test_storage_integration.py:21` | `pytest.mark.skipif(not all(S3_* env vars), ...)` | S3/Garage not configured | Configure S3 env vars |
| `tests/integration/test_exploit_db_integration.py:30` | `pytest.mark.skipif(not NETWORK_TESTS, ...)` | Network tests disabled | Set `NETWORK_TESTS=1` |
| `tests/integration/test_live_scan.py:144,157,169` | `pytest.skip("Cannot reach vuln-web directly from test runner")` | Network reachability | Ensure vuln-web container is running |
| `tests/integration/test_tool_execution.py:322` | `@pytest.mark.skipif(not tool_is_available("nmap"), ...)` | nmap not installed | Install nmap in test runner |
| `tests/integration/test_tool_execution.py:329` | `pytest.skip("nmap plugin not loaded")` | nmap plugin not loaded | Ensure nmap plugin loads |
| `tests/integration/test_tool_execution.py:346` | `@pytest.mark.skipif(not tool_is_available("nuclei"), ...)` | nuclei not installed | Install nuclei |
| `tests/integration/test_tool_execution.py:519` | `@pytest.mark.skipif(os.geteuid() != 0, ...)` | Not root | Run as root (for tool installation) |
| `tests/integration/test_tools_container.py:114` | `pytest.skip("Plugins directory is read-only")` | Read-only filesystem | Mount writable plugins directory |
| `tests/integration/test_live_targets.py:80` | `pytest.skip("Live tests require real LLM provider (AI_PROVIDER != mock)")` | Mock LLM in use | Set real LLM provider |
| `tests/integration/test_ops_scripts_live.py:31` | `pytest.skip("docker CLI is required for live ops smoke tests")` | docker CLI missing | Install docker CLI |
| `tests/integration/test_ops_scripts_live.py:43` | `pytest.skip(f"live ops smoke tests require env vars: {missing}")` | Missing env vars | Set required env vars |
| `tests/integration/test_ops_scripts_live.py:51` | `pytest.skip(f"required live containers are unavailable: {unavailable}")` | Containers not running | Start required containers |
| `tests/e2e/test_api_live.py:18` | `@pytest.mark.skipif(not APP_BASE_URL, ...)` | APP_BASE_URL not set | Set APP_BASE_URL |
| `tests/e2e/test_api_live.py:38` | `pytest.skip(f"Cannot authenticate (status {resp.status_code})")` | Auth failed | Check credentials |
| `tests/e2e/test_full_api_workflow.py:37` | `pytest.skip("API server not running - start with: docker compose up -d")` | API not reachable | Start API server |
| `tests/e2e/test_full_api_workflow.py:83` | `pytest.skip("Authentication failed - check server logs")` | Auth failed | Check server logs |
| `tests/e2e/test_full_api_workflow.py:330` | `pytest.skip(f"Could not start mission: {response.text}")` | Mission start failed | Investigate mission startup |
| `tests/e2e/test_full_api_workflow.py:387` | `pytest.skip(f"Could not create target: {response.text}")` | Target creation failed | Investigate target creation |
| `tests/e2e/ui/harness/db_user.py:75,118` | `pytest.skip("DATABASE_URL not set")` | DATABASE_URL not in env | Set DATABASE_URL |
| `tests/e2e/ui/conftest.py:428` | `pytest.skip("DATABASE_URL not set")` | DATABASE_URL not in env | Set DATABASE_URL |
| `tests/e2e/ui/conftest.py:446` | `pytest.skip(f"Could not seed manual_mode: {result['error']}")` | DB seed failed | Investigate DB seed |
| `tests/e2e/ui/test_mobile_layout.py:110` | `pytest.skip("User does not have admin access")` | Admin access needed | Grant admin role to test user |
| `tests/platform_harness.py:98` | `pytest.skip(_platform_targets_skip_message(...))` | Platform targets unreachable | Start platform targets |
| `tests/platform_harness.py:108` | `pytest.skip("Recovery-window assertions are disabled by default; set LOAD_TEST_ENABLE_RECOVERY_WINDOWS=1")` | Feature flag off | Set `LOAD_TEST_ENABLE_RECOVERY_WINDOWS=1` |
| `tests/platform_harness.py:125` | `pytest.skip("Load test rate-limit reset was requested, but redis-py is unavailable")` | redis-py not installed | Install redis-py |
| `tests/platform_harness.py:135` | `pytest.skip("Load test isolation requires a reachable Redis rate-limit backend")` | Redis unreachable | Start Redis |
| `tests/platform_harness.py:213` | `pytest.skip("Load user provisioning requires email verification to be disabled in the test stack")` | Email verification enabled | Disable email verification in test stack |

### 2.2 Highest-Priority Skip

**`tests/integration/test_agents_integration.py`** — Entire file is permanently skipped with `pytestmark = pytest.mark.skip(reason="Mock LLM provider not implemented")`. The mock LLM exists in `tests/mocks/llm.py`, so this appears to be an abandoned/outdated skip reason. **Should be un-skipped** once the agent integration tests are verified to work with the existing MockLLMClient.

---

## 3. Flaky Tests — Root Causes

### 3.1 Hard-Coded Sleeps (`time.sleep`)

| File | Line | Duration | Issue |
|------|------|----------|-------|
| `tests/integration/test_live_targets.py` | 490 | 3s | Polling wait for mission status |
| `tests/integration/test_live_targets.py` | 521 | 1s | Polling wait |
| `tests/unit/core/test_security_features.py` | 65 | 0.1s | Token expiry test |
| `tests/unit/core/test_security_features.py` | 75 | 1.1s | Token expiry test |
| `tests/unit/test_mission_runtime_features.py` | 350 | 0.01s | Minor delay |
| `tests/e2e/ui/conftest.py` | 164 | 2s | Auth retry backoff |
| `tests/e2e/ui/test_user_scenarios.py` | 40 | N/A | Comment only: "Redirect loop — clear cookies, re-inject from context, retry" |

### 3.2 Retry Logic in Tests (Not Production Code)

Multiple tests explicitly test retry behavior (`test_retry_succeeds_on_second_attempt`, `test_retryable_vectors_are_retried`, etc.). These are **intentional** — they verify the retry mechanism works. However, tests like `test_retry_exhausted_raises` can be inherently "flaky" if backoff timing is tight.

### 3.3 Tests Depending on External State

- **`test_live_scan.py`** (lines 144, 157, 169): Tests that hit `http://vuln-web` directly depend on network routing from the test runner container to the vuln-web container. Flaky if container networking isn't configured.
- **`test_exploit_db_integration.py`**: NVD/CISA/EPSS network tests depend on external APIs and respect a 2-second rate-limit buffer. Flaky if NVD API rate limits are hit.
- **`tests/soak/test_mixed_traffic_stability.py`**: Uses `asyncio.sleep(pause_seconds)` between iterations. Flaky if under load.
- **`test_real_tool_workflow.py`**: Tests tool execution against real targets (metasploitable, dvwa). Flaky if targets aren't healthy.

### 3.4 Auth-Related Flakiness (Playwright UI Tests)

`tests/e2e/ui/test_user_scenarios.py` has a comment on line 40:
```python
# Redirect loop — clear cookies, re-inject from context, retry
```
This workaround pattern indicates **redirect loop flakiness** after cookie re-authentication. The `authenticated_page` fixture has elaborate re-auth logic (lines 291–323 of `conftest.py`) with a 3-retry loop and 1-second sleep. Root cause: session/cookie expiry timing is non-deterministic.

### 3.5 Recommendations to Fix Flakiness

1. **Replace `time.sleep` with async polling helpers**: Use `asyncio.wait_for` with a poll interval instead of fixed sleeps.
2. **Increase auth retry backoff**: The 2-second sleep in `_build_auth_cookies` (conftest.py:164) and 1-second sleep in re-auth (line 321) may still be insufficient under slow CI environments. Consider exponential backoff.
3. **Make `test_live_scan.py` network tests conditional**: Already uses try/except for reachability, but the vuln-web container must be reliably routable from the test-runner network.
4. **Add `@pytest.mark.flaky`**: Consider using `pytest-flaky` plugin to automatically retry UI tests that fail due to timing.
5. **Isolate Playwright tests from auth state**: The shared context + cookie clearing approach works but is fragile. Consider using API token-based auth instead of cookie-based for tests where possible.

---

## 4. Test Coverage

### 4.1 Configuration

- **Tool**: `pytest-cov` configured in `pyproject.toml`
- **Coverage fail-under threshold**: `67.4%` (line 94 of `pyproject.toml`)
- **Source**: `app/` (excluding migrations, alembic, tests, scripts)
- **Report**: `term-missing` + XML

### 4.2 Current Coverage

CI runs unit tests with `--cov-fail-under=67.4`. This is a **relatively low bar** — only 67.4% line coverage is required. For a security-critical application, this should ideally be 80%+ for critical paths.

### 4.3 Critical Paths Likely Untested

Based on the project description, these areas may be under-tested:
- **Plugin signature verification** (`app/services/plugin_management/`)
- **RAG knowledge base** (tests exist but are mostly skipped)
- **Multi-agent consensus/k-threshold voting** (`app/services/ai/consensus.py`)
- **Sandbox isolation and resource limits**
- **WebSocket reconnection logic**
- **Dead-letter queue handling**
- **Backup/restore functionality**

---

## 5. Test Data & Fixtures

### 5.1 Fixture Architecture

**Root conftest (`tests/conftest.py`)** provides 6 `autouse=True` session-scoped fixtures:
1. `cleanup_test_logs` — cleans `logs/spectra_testing.log`
2. `mock_websocket_for_unit_tests` — mocks broadcast, broadcast_event, emit_sync, background task loops
3. `disable_rate_limiting_for_unit_tests` — disables slowapi
4. `mock_llm_for_unit_tests` — injects `MockLLMClient`
5. `mock_database_for_unit_tests` — mocks `async_session_maker`
6. `mock_storage_for_unit_tests` — mocks S3 storage
7. `reset_service_singletons` — resets exploit_db and cve_intel singletons after each test

**Integration conftest (`tests/integration/conftest.py`)**:
- Disables rate limiting
- Mocks WebSocket broadcast
- Mocks DB session for ASGI transport tests
- Provides `mission_manager` with controlled scheduling (bypasses execution loop)

**E2E UI conftest (`tests/e2e/ui/conftest.py`)**:
- `authenticated_page` — session-scoped cookie auth with re-auth retry loop
- `fresh_authenticated_page` — isolated context per test
- `shared_context` — single browser context shared across tests
- `ensure_manual_mode_subscription` — seeds DB with manual_mode plan

### 5.2 Database Reset Between Tests

- Unit tests use `mock_database_for_unit_tests` (no real DB)
- Integration tests mock `async_session_maker` but don't reset between tests
- E2E UI tests use `DATABASE_URL` to reset user activity (`_reset_user_activity`)
- Load/soak tests use actual PostgreSQL but some fixtures truncate queues (`test_queue.py:65`)

### 5.3 Race Conditions in Parallel Execution

**Potential issues**:
1. `mock_llm_for_unit_tests` patches module-level LLM client getters — if tests run in parallel and different tests need different mock configurations, they will interfere.
2. `reset_service_singletons` resets module singletons (`_instance`, `_cve_knowledge_base`) after each test — concurrent tests in the same process could race on singleton access.
3. `test_queue.py` creates unique queue names per test but doesn't guarantee cleanup order.
4. Load tests (`tests/load/`) use session fixtures but modify global rate-limit state.

**Verdict**: The autouse mocking approach works for sequential test execution. Parallel execution (`pytest-xdist`) with the current mocking strategy would likely cause failures due to shared module-level patches.

---

## 6. Playwright E2E Tests

### 6.1 Configuration

No `playwright.config.*` found. Playwright is configured via `pytest.ini_options` in `pyproject.toml` and `tests/e2e/ui/conftest.py`. The UI test runner uses:
```bash
docker compose ... run --rm ui-test-runner tests/e2e/ui/ -v --tb=short -x --no-cov
```

The `ui-test-runner` is built from `docker/Dockerfile.playwright` (referenced in `run_ui_tests.sh`).

### 6.2 Test Coverage

**Covered**:
- Multi-role access (admin vs regular user)
- Dashboard, sidebar navigation, profile, settings, admin panels
- User registration, login, rate-limit behavior
- Mission launch form, GDPR features, branding, mobile layout
- Release candidate flows

**Missing/Untested**:
- WebSocket real-time updates (live connection, reconnection)
- Plugin management via UI
- Full mission execution flows (only form fill is tested, not actual mission run)
- Billing/payment flows
- LDAP/OIDC integration flows
- File upload functionality
- Dark mode / theme switching

### 6.3 Selector Robustness

Playwright tests mix CSS selectors (`#sidebar`, `#mission-target`, `.admin-sidebar [data-section='users']`) with `data-section` attributes. No `data-testid` attributes found — selectors are fragile and couple tests to CSS structure.

### 6.4 Waits

The test configuration uses:
- `page.goto(..., wait_until="domcontentloaded")` — generally correct
- `expect(locator).to_be_visible(timeout=...)` — good practice
- `page.wait_for_timeout(1000)` — **anti-pattern** (line 85 in `test_user_scenarios.py`) — used for "wait for table to populate"

### 6.5 Auth Suppression Script

Lines 45–73 of `conftest.py` inject an init script that **suppresses 401→/login redirects** by wrapping `window.fetch`. This is a creative workaround for Playwright/Chrome race conditions but masks real auth failures in tests.

---

## 7. CI/CD Pipelines

### 7.1 `.github/workflows/ci.yml`

**Jobs**: lint → test → integration-test → security → docker-build → deps → version-check

**On**: push to main/develop + PRs to main

**Key observations**:
- **Lint**: Runs ruff check + import boundary check in Docker
- **Unit tests**: Runs in Docker with coverage, fail-under=67.4
- **Integration tests**: Run with `-k 'not live and not e2e'` (skips live integration tests)
- **Security**: Bandit scan with HIGH severity + HIGH confidence
- **Docker build**: Verifies all 5 Dockerfiles build + Trivy CVE scan (CRITICAL only)
- **Deps**: pip-audit with `--fix --dry-run` (soft enforcement, uses `|| true`)
- **Version check**: Verifies `app/_meta/version.py` has `__version__`

**Gaps**:
- Integration tests **skip all `@pytest.mark.live` tests** (`-k 'not live and not e2e'`)
- Playwright UI tests are **NOT run** in CI (only in `ui-e2e.yml` workflow, which is path-triggered)
- No benchmark/performance regression gating
- `pip-audit --fix --dry-run || true` — vulnerabilities don't block CI

### 7.2 `.github/workflows/ui-e2e.yml`

**Triggered by**: path changes to `templates/**`, `static/**`, `tests/e2e/**`, `run_ui_tests.sh`, `Dockerfile.playwright`, `Dockerfile.api`, `docker-compose.test.yml`

**Timeout**: 120 minutes

**Verdict**: Good path-based triggering to avoid unnecessary runs. Full Playwright suite runs on relevant changes.

### 7.3 `.github/workflows/release.yml`

**Pre-deploy gates** (lines 79–93):
1. Build unit-test-runner + test-runner
2. Validate `tensorzero.toml`
3. Run unit tests with coverage (fail-under=67.4)
4. Run integration tests (`-k 'not live and not e2e'`)
5. Security scan (bandit HIGH+HIGH)
6. Docker Compose config validation
7. Trivy CVE scans on all 5 images

**Gaps**:
- Integration tests skip live tests (same as CI)
- UI E2E tests NOT run pre-release (only when path changes trigger `ui-e2e.yml`)
- No soak/load tests

### 7.4 Secrets Handling

- `ENCRYPTION_KEY: test-encryption-key` — hardcoded in workflows (line 32 of ci.yml, line 44 of ui-e2e.yml). This is a test key, acceptable.
- Deployment secrets use GitHub Actions secrets (`secrets.DEPLOY_*`)
- GHCR login uses `GITHUB_TOKEN` (provided by GitHub)

### 7.5 Security Gates

**Strengths**:
- Bandit (security linter) enforced (exits 1 on HIGH+HIGH findings)
- Trivy CVE scanning on all Docker images (CRITICAL only, exits 1)
- Dependency audit via pip-audit

**Weaknesses**:
- pip-audit is soft-enforced (`|| true`)
- No SAST tool (Bandit is basic)
- No secret scanning on commits
- No malware scanning on plugin files

---

## 8. Benchmarks & Performance Tests

### 8.1 Existing Benchmarks

1. **`tests/performance/test_api_latency.py`**: Parametrized latency smoke tests for `/api/health`, `/api/auth/setup/status`, `/api/auth/me`. Thresholds configurable via env vars (`PERF_HEALTH_P50_MS`, etc.). Marked `@pytest.mark.performance`.

2. **`tests/load/`**: 7 burst/load test files covering:
   - Password reset bursts
   - Rate limit bursts
   - Multi-replica rate limit sharing
   - Recovery windows
   - WebSocket churn
   - Tool worker concurrency

3. **`tests/soak/test_mixed_traffic_stability.py`**: Mixed-traffic soak harness. Marked `@pytest.mark.soak`.

### 8.2 Automation

- **NOT in CI**: Performance/load/soak tests are **not run in any CI workflow**
- **Manual trigger**: `./tests/run_load_tests.sh` for load/performance/soak
- **Live smoke**: `./tests/run_live_tests.sh` for live integration

**Verdict**: Performance regression testing is entirely manual and not enforced in CI. This is a significant gap — performance regressions would only be caught if someone manually runs the harness.

---

## 9. Linting & Formatting

### 9.1 Configuration (`pyproject.toml`)

**Ruff** (lines 14–56):
- `target-version = "py311"`
- `line-length = 120`
- 10 rule groups enabled: `E, F, W, I, S, B, UP, C4, SIM, PIE, RUF, PLE, PLW`
- 22 ignored rules including `E501` (line too long), `S101` (assert), security-related ignores for tests

**Pyright** (lines 58–62):
- `pythonVersion = "3.11"`
- `typeCheckingMode = "basic"`
- `reportMissingImports = none`
- `reportMissingModuleSource = none`

### 9.2 Enforcement

**In CI (`ci.yml`, line 24)**:
```bash
docker run --rm spectra-test-ci python -m ruff check app/ tests/
```
Ruff check is run against both `app/` and `tests/` — no auto-fix, just check. This is a **hard gate** (exits 1 on findings).

### 9.3 Type Errors

No `mypy` configuration found. Pyright is configured but **not run in CI**. The `pyright` check in CI is absent.

---

## 10. Dependencies

### 10.1 Testing Dependencies (`requirements/dev.txt`)

```
pytest==9.0.2
pytest-asyncio==0.24.0
pytest-cov==7.0.0
pytest-dotenv==0.5.2
pytest-timeout==2.3.1
aiosqlite==0.22.1
playwright==1.58.0
pytest-playwright==0.7.2
aiohttp==3.13.5
aiofiles==25.1.0
```

### 10.2 Known Issues

1. **No upper bound on `pytest-playwright`**: 0.7.2 is quite old (current is ~0.6.x). Could cause compatibility issues.
2. **`aiohttp==3.13.5`**: aiohttp 3.13.x is very recent; less battle-tested than 3.9.x LTS.
3. **No pip-audit in requirements**: pip-audit is only installed ad-hoc in CI (`pip install pip-audit`).

### 10.3 Vulnerability Status

CI runs `pip-audit --fix --dry-run -l --ignore-vuln PYSEC-2024-65 --ignore-vuln PYSEC-2024-66 || true`. The `|| true` means vulnerabilities don't block CI. This is a **soft gate**.

---

## Summary Table

| Category | Status | Notes |
|----------|--------|-------|
| Test Structure | ✅ Good | Well-organized tiers with dedicated conftest.py per tier |
| Skipped Tests | ⚠️ 38 skips | 1 permanently skipped file; 37 conditionally skipped |
| Flaky Tests | ⚠️ Moderate | Hard-coded sleeps, auth retry loops, network dependency |
| Test Coverage | ⚠️ Low bar | 67.4% fail-under; should be 80%+ for security app |
| Test Fixtures | ✅ Good | Autouse fixtures per tier; proper mocking isolation |
| Parallel Execution | ❌ Risky | Module-level patches prevent safe parallel execution |
| Playwright E2E | ⚠️ Partial | Good selector patterns but fragile CSS selectors |
| CI/CD Unit/Integration | ✅ Good | Comprehensive with CVE scanning |
| CI/CD Playwright | ⚠️ Path-triggered | Only runs on path changes, not every PR |
| Benchmarks | ❌ Manual only | Performance tests not in CI |
| Linting | ✅ Good | Ruff enforced in CI |
| Dependencies | ⚠️ Soft audit | pip-audit doesn't block CI |

---

## Top Priority Fixes

1. **Un-skip `test_agents_integration.py`**: Replace `"Mock LLM provider not implemented"` skip with actual mock provider verification.
2. **Increase coverage threshold**: Move from 67.4% to 80% for critical paths.
3. **Add performance tests to CI**: At minimum, run `test_api_latency.py` in CI with thresholds.
4. **Replace `time.sleep` with async polling**: Eliminate fixed sleeps in favor of `asyncio.wait_for` with polling.
5. **Enable pytest-xdist with fixture isolation**: Current autouse mocking breaks parallel execution — either fix isolation or document that parallel execution is not supported.
6. **Add `data-testid` attributes**: Replace fragile CSS selectors with `data-testid` for Playwright tests.
7. **Make pip-audit a hard gate**: Remove `|| true` from pip-audit in CI.
8. **Run Playwright UI tests on every PR**: Currently only path-triggered — consider running on every PR with a time budget.
