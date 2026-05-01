# Runbooks

Operator and developer **executable** procedures for Spectra. Prefer these paths over ad-hoc commands so local runs, VPS checks, and CI stay aligned.

| Runbook | Purpose |
| --- | --- |
| [CI parity (local / VPS)](ci-parity-local.md) | Same gates as `.github/workflows/ci.yml` lint + test jobs: Ruff, import boundaries, Pyright, unit coverage ≥70%, settings runner, optional integration. |
| [Pre-release gate](pre-release-gate.md) | Checklist before production: CI parity, compose config, smoke paths, rollback awareness. |
| [Legacy cleanup backlog](legacy-cleanup-backlog.md) | Tracked removals: deprecated env vars, type aliases, global toast API — not a substitute for CI. |

Canonical wiki context: [Testing strategy](../wiki/testing-strategy.md), [Operations](../wiki/operations.md), [Development](../wiki/development.md).

## One-command CI mirror

From the repository root (Docker required):

```bash
./scripts/runbooks/ci-parity.sh ci
```

Full gate including integration tests (starts Garage, longer):

```bash
./scripts/runbooks/ci-parity.sh all
```

Faster iteration (skip Pyright):

```bash
SKIP_PYRIGHT=1 ./scripts/runbooks/ci-parity.sh ci
```
