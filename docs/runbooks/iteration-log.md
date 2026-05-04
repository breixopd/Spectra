# Platform quality iteration log

Short-lived audit memory for **audit → research → implement** cycles. Older numbered-loop history was removed on 2026-05-01 after items were merged, fixed, or moved to `legacy-cleanup-backlog.md`.

## Recently closed (examples)

- CI: single **`static-analysis`** job; runbooks/wiki aligned with real `ci.yml` / `release.yml` behaviour.
- Billing: Stripe **`charge.refunded`** reconciliation + tests; VPN disabled-gate test; ScopeAgent **`max_hosts`** tests.
- Secrets: **`SystemConfig`** encrypt/decrypt narrowed; scheduler scaling dashboard dead **`try/except`** removed.
- P0 backlog: **`WORKER_SKIP_STARTUP_AUTO_INSTALL`** removed (dead env + duplicate test); **`ExploitInput` / `ExploitAction`** aliases removed in favour of **`ExploitCrafterInput`** / **`ExploitCrafterOutput`**.

## Open / next

See **`legacy-cleanup-backlog.md`** for P1/P2 surface-area items (toast API, `manual_helpers`, `install_timeout` compat param, etc.).

Before a release tag: **`./scripts/runbooks/ci-parity.sh ci`** (or **`all`** with integration when time allows).
