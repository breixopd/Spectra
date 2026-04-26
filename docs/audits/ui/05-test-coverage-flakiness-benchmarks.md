# UI Audit: Test Coverage, Flakiness, Benchmarks

Status: loop 4 in progress
Scope: Playwright, Docker test runners, live smoke, skipped tests, warnings, performance/UX benchmarks.

## Current Verified Baseline

- UI suite: `90 passed, 1 skipped` in Docker on the VPS.
- Unit suite: `3552 passed`, with remaining runtime warnings from mocked async paths.
- Integration subset: `76 passed, 8 skipped`.
- Live smoke: passed after resetting the VPS test admin credentials.
- Recent compose log scan found no warning/error/traceback matches in service logs.

## Findings

- Some tests are skipped because they intentionally require unavailable conditions such as specific entitlements, live LLM/provider access, or long-running external target/mission flows. These should be split into explicit test profiles instead of appearing as ambiguous skips.
- Playwright fixtures still rely on custom cookie handling and repeated login verification. This works, but role/plan matrix testing would be less flaky with role-specific isolated auth states or deterministic per-test API setup.
- Some UI tests still use CSS IDs/selectors where role, label, or explicit `data-testid` contracts would be more robust.
- There is no systematic UI benchmark suite for task completion time, page load, route hydration, or mission UI responsiveness.
- Remaining unit warnings from async mocks create noise and can hide real resource lifecycle issues.

## Research Notes

- Playwright best practice is to prefer user-facing locators (`getByRole`, labels, text) and use test IDs only when no stable accessible contract exists.
- Each role should have isolated authenticated state. Multi-role flows should use separate browser contexts rather than reusing mutable cookies.
- Flaky tests should be fixed by waiting for business conditions and stable UI states, not by broad sleeps or large global timeouts.

## Recommended Work

- Define explicit Docker test profiles:
  - unit
  - integration
  - ui
  - live-smoke
  - live-mission
  - load/performance
  - accessibility
  - provider-dependent
- Convert ambiguous skips to explicit markers and CI jobs with clear prerequisites.
- Add role/plan fixture factory:
  - admin enterprise
  - staff enterprise
  - user free
  - user professional
  - user enterprise
  - processing restricted user
  - API-access user
  - no-manual-mode user
- Add benchmark tests for:
  - login to dashboard time
  - dashboard data hydration
  - admin plan editor open/save
  - report list/render
  - mission event stream latency under synthetic events
- Add a warning budget gate. New warnings should fail the relevant test job; existing warnings should be tracked down and removed.

## Verification Targets

- `pytest -ra` output explains every skip.
- No broad "skip if cannot authenticate" paths in core verification jobs.
- UI tests run deterministically from clean Docker state and do not depend on prior test order.

## Loop 1 Fixes Applied

- Fixed the manual-mode Playwright fixture so it no longer passes parameters into a PostgreSQL `DO $$` block.
- `test_manual_tools_page` now runs and passes instead of skipping due to fixture setup failure.
- Sidebar navigation tests now accept canonical in-page hash navigation for tabbed pages such as `/manual#manual-tabs-execute`.

## Why Some Tests Are Skipped (and how to run “everything”)

Skips fall into a few buckets:

| Bucket | Example | Can we unskip in default CI? |
|--------|---------|------------------------------|
| Optional integrations | RAG tests when embeddings not seeded | Only in a job that provisions vector data |
| Live / expensive | Full mission flow against real LLM + DB | Separate `live-mission` or manual job; needs keys and time |
| Entitlement setup | Admin-only flows when no admin token | Already handled in UI stack; use `pytest -ra` to list reasons |
| Provider mock | `require_real_llm` in `test_live_targets` | Run with real `AI_PROVIDER` and working OpenRouter key in env |

**Running every test in one command is possible but not recommended:** the default “verify” job would pull in long-running network tests, flaky external rate limits, and env-specific infrastructure. Instead, use **layered jobs** (unit → integration subset → UI → live) and treat `pytest -m "not live"` (or project-specific markers) as the default gate.

To see all skip reasons in one run: `pytest -ra tests/`.

## Loop 2 — CI and Playwright

- **GitHub Action** `.github/workflows/ui-e2e.yml` runs `tests/run_ui_tests.sh` on path-scoped PRs, `main` / `develop` pushes, and `workflow_dispatch` (not part of the default every-file CI gate, to keep PR feedback fast).
- **`tests/run_ui_tests.sh`**: Playwright now uses `APP_BASE_URL=http://app:5000` (same Docker network as the API). The previous `host.docker.internal:15000` was invalid with the default compose (no service on that host port); use Caddy on `localhost:15080` only for manual cross-browser testing.
- **`test_multi_role`**: user creation uses full-UUID usernames and retries on HTTP 409 instead of skipping, reducing ambiguous skips and collision edge cases.

## Loop 3 — Entitlement E2E + shared harness

- **`tests/e2e/ui/harness/db_user.py`**: shared DB seeding (verified users, plan `features` JSON) and `ui_login` for Playwright.
- **`tests/e2e/ui/test_entitlement_sidebar.py`**: sidebar `data-entitlement-gate` matrix (api_access, manual_mode) including admin bypass and upgrade link visibility.
- **`test_release_candidate_flows.py`**: refactored to use the harness (less duplication).
- **Docs:** `09-entitlement-ui-patterns.md`, `10-product-ux-hardening-checklist.md`, `11-pytest-skip-inventory.md`, `architecture/04-missions-core-router-split.md`.
- **Skips:** “Run every test in one CI job” is still discouraged; `11-pytest-skip-inventory.md` lists reasons and the intended layered jobs.

## Loop 4 — Subagent pass + missions catalog module

- Three **explore** subagents in parallel: e2e coverage gaps / flakiness patterns, missions router split plan, pytest skip inventory by CI job.
- **Refactor:** `app/api/routers/missions/mission_catalog.py` holds literal-path routes (`/presets`, `/summary`, …) merged **before** `core` in `__init__.py`; `CreateChainRequest` re-export moved to `mission_catalog`.
