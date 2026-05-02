# Legacy and compat backlog (inventory)

Last full pass: exploratory audit of the repo (not a guarantee nothing else exists). Use this as a **backlog** for removing customer-facing ambiguity and dead switches—not as a release blocker by itself.

## P0 — Remove or replace when safe

_(empty — last P0 items were cleared 2026-05-01: worker startup env switch, exploit crafter type aliases.)_

## P1 — Reduce surface area

_(empty — `_spectraToast` removed May 2026: classic scripts use `window.showToast`; ESM `import { showToast }` from `/static/js/modules/toast.js`.)_

## P2 — Docs / data migrations

- Terminology “monolith” in comments/docs; encryption **legacy** key derivation (keep until ciphertext migrated); billing **legacy_plan_id** paths in rollback/entitlements.

## What is already clean

- Domain code lives in **`packages/platform/src/spectra_platform/`** (Python package **`spectra_platform`**, workspace **`spectra-platform`**); HTTP surface is **`services/api/src/spectra_api/`** only — no duplicate `templates/` / `static/` at repo root.
- No `sys.modules` import shims in `spectra_platform/`, `services/`, `packages/`.
- Worker startup does not read **`WORKER_SKIP_STARTUP_AUTO_INSTALL`**; tools container only syncs registry tool status on boot.

- Toasts: **`window.showToast`** (stub in `confirm.js`, real impl in `modules/toast.js`); no **`_spectraToast`**.

When an item is completed, delete or shrink its section here and point to the PR in the changelog.
