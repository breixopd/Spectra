# Legacy and compat backlog (inventory)

Last full pass: exploratory audit of the repo (not a guarantee nothing else exists). Use this as a **backlog** for removing customer-facing ambiguity and dead switches—not as a release blocker by itself.

## P0 — Remove or replace when safe

- **`WORKER_SKIP_STARTUP_AUTO_INSTALL`** — marked deprecated in `services/worker/src/spectra_worker/lifecycle.py`; still in `docker/compose.yaml`, tests, and `docs/wiki/worker-system.md`. Remove end-to-end once bulk install at startup is gone.
- **`MissionState = MissionStatus` alias** — `app/mission/core/state_machine.py`; update tests/callers then delete.
- **`ExploitInput` / `ExploitAction` aliases** — `app/services/ai/agents/exploit_crafter.py`; migrate `app/services/mission/exploitation.py` and drop aliases.

## P1 — Reduce surface area

- Global **`_spectraToast`** legacy API — `services/api/static/js/modules/toast.js` and callers; migrate to ESM `showToast`.
- **`manual_helpers` legacy template field** — `services/api/src/spectra_api/api/routers/manual_helpers.py`.
- **`install_timeout` unused compat param** — `app/services/tools/validation.py`.
- **`asyncssh` shim** in provisioner when dependency is guaranteed — `app/services/provisioning/provisioner.py`.

## P2 — Docs / data migrations

- Terminology “monolith” in comments/docs; encryption **legacy** key derivation (keep until ciphertext migrated); billing **legacy_plan_id** paths in rollback/entitlements.

## What is already clean

- No `app/api/` tree; no duplicate `templates/` / `static/` at repo root (canonical under `services/api/`).
- No `sys.modules` import shims in `app/`, `services/`, `packages/`.

When an item is completed, delete or shrink its section here and point to the PR in the changelog.
