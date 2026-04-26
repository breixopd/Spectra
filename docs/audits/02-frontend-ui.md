# Frontend UI Audit

## Critical / High

- UI uses two models at once: classic global scripts and `type="module"` scripts. Admin/manual-tools/dashboard pages mix globals, delegated actions, and module entrypoints.
- Browser coverage is behind admin surface. Admin sidebar includes usage, scaling, LLM, TensorZero, backups, rollback, services, plans, users, and audit, but tests cover only a smaller fixed set.
- First-run setup and billing flows have little or no Playwright coverage.

## Cleanup Opportunities

- Consolidate shared helpers (`escapeHtml`, `formatDate`, API wrappers) into `app/static/js/modules/`.
- Collapse admin JS behind one module entrypoint per page or one admin shell module.
- Remove or use `app/templates/macros/layout.html`; it appears unused.
- Move root-level JS entrypoints into `pages/` or `modules/` so service/UI code has clearer ownership.

## Recommended Tests

- Browser smoke for `/setup`.
- Browser smoke for profile billing buttons/checkout/portal error states.
- Admin tab coverage generated from `data-section` entries, so new tabs cannot silently miss tests.
