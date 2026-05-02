# Scripts layout + quality pass (2026-05-02)

## Scope

- **Scripts directory:** deduplicate CI unit entrypoints, document layout, remove unused Python package glue.
- **Verification:** Docker-first gates per repo rules; OpenRouter credentials only in gitignored `.env.test` (local + VPS), never committed.

## Changes made

| Item | Action |
|------|--------|
| `scripts/__init__.py` | **Removed** — unused (`init_script_services` had no callers); `scripts.check_import_boundaries` still imports via PEP 420 namespace package. |
| `scripts/ops/run_unit_tests_docker.sh` | **Thin wrapper** → `scripts/runbooks/ci-parity.sh unit` (single source of truth with CI). |
| `scripts/ops/vps-verify-tests.sh` | **Thin wrapper** → same `ci-parity.sh unit` (removed duplicated compose/pytest). |
| `scripts/README.md` | **Added** — map of runbooks, ops, wrappers, and links to docs. |
| `scripts/ops/README.md` | **Updated** — pointer to scripts map + note that VPS helpers delegate to `ci-parity.sh unit`. |

## Security / secrets

- API keys must live in **`.env.test`** (gitignored) or the host secret store — not in runbooks or compose-committed files.
- Keys shared in chat should be **rotated** in the provider dashboard.

## Re-run

- Full platform matrix: `./scripts/runbooks/full-test-matrix.sh`
- CI parity only: `./scripts/runbooks/ci-parity.sh all`
- VPS unit gate: `./scripts/ops/vps-verify-tests.sh`

## Residual (none for this pass)

No `OPEN:` items; follow-ups are product-scale (e.g. optional further consolidation of `deploy.sh` / `first_run.sh` is deferred until a dedicated deployment RFC).

## Additional fixes (Playwright + rate limits)

| Issue | Fix |
|-------|-----|
| `ui_login` sometimes timed out on dashboard | Wait for `POST /api/v1/auth/token` (assert `ok`), then dashboard URL + sidebar — `tests/e2e/ui/harness/db_user.py`. |
| Many logins → HTTP 429 `15/minute` | `.env.test.example` documents `RATE_LIMIT_LOGIN=500/minute`; `tests/run_ui_tests.sh` sets `ENV_FILE=$PROJECT_DIR/.env.test` so the app container receives test limits and keys. |

## Verification

- `./tests/run_ui_tests.sh` — **126 passed**, 2 skipped (dark mode).
- `./scripts/runbooks/full-test-matrix.sh` with `SKIP_*` (API e2e slice only) — **7 passed** (`tests/e2e/test_api_live.py`); worker service healthcheck given **`start_period: 120s`** and **`retries: 8`** in `docker/compose.yaml` so cold-start worker installs do not fail dependent services during marathon compose ups.

