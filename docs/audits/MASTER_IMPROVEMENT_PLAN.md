# Spectra Master Improvement Plan

**Date**: 2026-04-27
**Based on**: UI/UX Audit, Backend/API Audit, Tests/CI Audit, Architecture Audit, Best Practices Research

---

## Loop 1: Critical Security & Quick Wins

### Backend (Critical)
- [ ] **SEC-1**: Fix missing RBAC on `pause_mission` and `resume_mission` in `app/api/routers/missions/mission_lifecycle.py`
- [ ] **SEC-2**: Fix inconsistent ownership checks in `mission_lifecycle.py` and `core.py` — always query DB first
- [ ] **SEC-3**: Add database index on `missions.created_at`
- [ ] **SEC-4**: Enhance plugin execution blocklist (add `-o` output overwrite patterns)
- [ ] **SEC-5**: Add rate limiting to `/internal/metrics` endpoint

### Tests (Quick Wins)
- [ ] **TEST-1**: Un-skip `tests/integration/test_agents_integration.py` and verify with MockLLMClient
- [ ] **TEST-2**: Replace `time.sleep` calls with async polling helpers in test files
- [ ] **TEST-3**: Add `data-testid` attributes to critical UI elements for Playwright robustness
- [ ] **TEST-4**: Fix auth suppression script in `conftest.py` to not mask real failures

### UI/UX (Quick Wins)
- [ ] **UI-1**: Fix `og:image` mismatch (`.png` vs `.svg`) in `landing.html`
- [ ] **UI-2**: Add `lang="en"` to landing page `<html>`
- [ ] **UI-3**: Add `prefers-reduced-motion` override for hero preview animations
- [ ] **UI-4**: Add proper `<label for="...">` associations in `settings.html`

---

## Loop 2: Architecture & File Organisation

- [x] **ARCH-1**: Move `app/static/` to `static/` at project root
- [x] **ARCH-2**: Move `app/templates/` to `templates/` at project root
- [x] **ARCH-3**: Move `app/version.py` to `app/_meta/version.py`
- [x] **ARCH-4**: Move `app/ai_service.py` to `app/services/ai/__main__.py`
- [x] **ARCH-5**: Move `app/scheduler_service.py` to `app/services/scheduler/__main__.py`
- [x] **ARCH-6**: Move `app/worker_service.py` to `app/worker/__main__.py`
- [x] **ARCH-7**: Update all Dockerfiles, compose files, and imports to reflect new paths
- [x] **ARCH-8**: Update `check_import_boundaries.py` if needed
- [ ] **ARCH-9**: Verify `make check` passes after reorganization

---

## Loop 3: Component Reusability & UI Architecture

- [ ] **UI-5**: Create reusable `partials/modal.html` macro and replace 4+ inline modals
- [ ] **UI-6**: Unify CSS tokens into single `tokens.css` imported by `input.css` and `landing.css`
- [ ] **UI-7**: Decompose `dashboard.js` into ES modules (charts.js, findings.js, tasks.js as proper imports)
- [ ] **UI-8**: Add breadcrumbs to `dashboard.html`, `targets.html`, `history.html`
- [ ] **UI-9**: Create reusable `feature_gate` Jinja2 macro for server-side gating
- [ ] **UI-10**: Implement server-side feature gating middleware/decorator

---

## Loop 4: API Hardening & Separation of Concerns

- [ ] **API-1**: Add consistent RBAC to all mission endpoints (`pause`, `resume`, `create_exploit_chain`)
- [ ] **API-2**: Add eager loading (`selectinload`) for mission list queries to fix N+1
- [ ] **API-3**: Standardize error response shapes across all routers
- [ ] **API-4**: Version all admin/auth routes under `/api/v1/`
- [ ] **API-5**: Add Pydantic response models for `/attack-summary` and `get_adversary_playbooks`
- [ ] **API-6**: Extract large `scheduler_service.py` (40KB) into smaller submodules

---

## Loop 5: Test Suite Hardening

- [ ] **TEST-5**: Increase coverage threshold from 67.4% to 75% (intermediate step toward 80%)
- [ ] **TEST-6**: Add tests for plugin signature verification
- [ ] **TEST-7**: Add tests for multi-agent consensus/k-threshold voting
- [ ] **TEST-8**: Add tests for WebSocket reconnection logic
- [ ] **TEST-9**: Add tests for dead-letter queue handling
- [ ] **TEST-10**: Fix `pytest-xdist` compatibility or document parallel execution limitations
- [ ] **TEST-11**: Add `pytest-flaky` plugin and mark known flaky tests
- [ ] **TEST-12**: Replace `page.wait_for_timeout(1000)` anti-pattern with proper waits

---

## Loop 6: Playwright E2E Expansion

- [ ] **E2E-1**: Add WebSocket real-time update tests
- [ ] **E2E-2**: Add plugin management UI tests
- [ ] **E2E-3**: Add full mission execution flow tests (not just form fill)
- [ ] **E2E-4**: Add billing/payment flow tests
- [ ] **E2E-5**: Add dark mode / theme switching tests
- [ ] **E2E-6**: Add file upload functionality tests
- [ ] **E2E-7**: Add multi-role matrix tests (admin, operator, viewer across all pages)
- [ ] **E2E-8**: Add plan limitation tests (free vs pro vs enterprise)

---

## Loop 7: Performance & Optimisation

- [ ] **PERF-1**: Add Redis caching layer for frequent DB queries
- [ ] **PERF-2**: Optimize `output.css` bundle size (Tailwind purge/tree-shaking)
- [ ] **PERF-3**: Add database query profiling and slow query logging
- [ ] **PERF-4**: Add in-memory caching for tool status and registry
- [ ] **PERF-5**: Add `pytest-benchmark` for critical path benchmarks
- [ ] **PERF-6**: Add performance regression tests to CI

---

## Loop 8: CI/CD & Security Hardening

- [x] **CI-1**: Make pip-audit a hard gate (remove `|| true`)
- [x] **CI-2**: Add Pyright type checking to CI
- [x] **CI-3**: Add pre-commit hooks for ruff and import boundary checks
- [x] **CI-4**: Add image scanning (Trivy) to CI pipeline
- [x] **CI-5**: Run Playwright UI tests on every PR (with time budget)
- [x] **CI-6**: Add secret scanning (GitHub Advanced Security)
- [x] **CI-7**: Add SBOM generation to release pipeline
- [x] **CI-8**: Add performance smoke tests to CI

---

## Loop 9: Documentation & Developer Experience

- [ ] **DOCS-1**: Update wiki to reflect current `SERVICE_MODE` architecture
- [ ] **DOCS-2**: Merge/resolve `deployment.md` vs `deployment-guide.md` confusion
- [ ] **DOCS-3**: Add architecture diagrams (C4 model or similar)
- [ ] **DOCS-4**: Document `data-on-submit` and `data-action` delegation patterns
- [ ] **DOCS-5**: Add design token documentation
- [ ] **DOCS-6**: Update CONTRIBUTING.md to reflect current requirements structure

---

## Loop 10: Final Verification & Integration

- [ ] **FINAL-1**: Run full test suite (unit + integration + e2e)
- [ ] **FINAL-2**: Run live mission against vuln container (if OpenRouter rate limits allow)
- [ ] **FINAL-3**: Run performance benchmarks
- [ ] **FINAL-4**: Run security scan (bandit, pip-audit, Trivy)
- [ ] **FINAL-5**: Verify all Docker images build
- [ ] **FINAL-6**: Verify `make check` passes
- [ ] **FINAL-7**: Run load/soak tests against VM
- [ ] **FINAL-8**: Final commit and summary

---

## Execution Notes

- **Parallel Execution**: Each loop will use multiple subagents running in parallel
- **Commits**: Commit after every loop, or after every major change set
- **Validation**: Run `lsp_diagnostics`, `ruff check`, and relevant tests after each change
- **VM Testing**: Use root@103.47.224.118 for live integration and load tests
- **Fallback**: If any task is too complex for a single loop, split it into sub-loops
