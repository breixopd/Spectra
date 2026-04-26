# UI Audit: Test Coverage, Flakiness, Benchmarks

Status: loop 1 draft
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
