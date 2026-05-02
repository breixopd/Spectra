# Tests & CI (read-only)

**Scope:** `.github/workflows/ci.yml`, `pyproject.toml` (pytest/coverage/pyright), `tests/integration` filters/skips.

## CI

| Job | Env | Highlights |
|-----|-----|--------------|
| **static-analysis** | Docker `Dockerfile.test` | ruff `packages/platform/src/spectra_platform tests/ services/ packages/`, import boundaries, pyright, Bandit |
| **test** | Compose `test` profile | unit pytest + `--cov=…` including `spectra_ai` and `spectra_scheduler`, fail-under 70; tensorzero parse; settings runner |
| **integration-test** | Compose app+test | Garage bootstrap; `tests/integration/` with `-k 'not live and not e2e'`, `--override-ini=addopts=` |
| **docker-build** | Host | Compose + Swarm validate; image builds; Trivy CRITICAL |
| **deps** | Host | pip-audit (ignored vulns listed in workflow) |
| **compose-smoke** | Push `main`/`develop` after unit+integration | Full stack → e2e API live, health live, perf smoke |

PRs to `main` skip compose-smoke (push-only gate).

## Markers (`[tool.pytest.ini_options]`)

`asyncio`, `e2e`, `integration`, `load`, `slow`, `live`, `network`, `performance`, `soak`, `timeout`, `ui`, `property`. CLI default: `--strict-markers`; default `addopts` enable coverage over `spectra_platform`, `spectra_api`, `spectra_worker`, `spectra_ai`, `spectra_scheduler` unless `-m`/`-k`/`--override-ini=addopts=` (used in CI for integration and compose-smoke slices).

## Coverage (`spectra_ai`)

**Update (2026-05-02):** `[tool.coverage.run] source` and the CI unit job include **`spectra_ai`** (and `spectra_scheduler`); the historical gap in this audit run is closed.

## Compose-smoke coverage

**Update (2026-05-02):** `compose-smoke` pytest steps append `--override-ini=addopts=` so e2e / health-live / performance runs do not inherit the repo-wide `--cov-fail-under=70` (those suites only exercise a thin HTTP slice of the codebase).

## Integration: `-k 'not live and not e2e'`

Excludes `@pytest.mark.live` (e.g. `test_live_scan`, `test_ops_scripts_live`) and `@pytest.mark.e2e` in integration (e.g. `mission_flow`, `safety`, `steering`, `tool_execution`).

Additional skips by env/stack: Postgres/sqlite (`server_pool`, `rag`); RAG may skip without `fastembed`; S3 env (`storage_integration`); LLM keys / `SKIP_LLM_LIVE` (`llm_live`); **`APP_BASE_URL` missing from env** (`api_health_live` — compose-smoke sets it); tooling/root (`tool_execution`); network (`exploit_db_integration`).

## Pyright vs Docker

Static analysis in **`static-analysis`** runs **Pyright inside `Dockerfile.test`** (same image as Ruff/Bandit), matching container deps more closely than a bare-host toolchain. `[tool.pyright]` still uses **`typeCheckingMode="off"`** and excludes tests → limited signal.
