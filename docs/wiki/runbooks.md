# Runbooks (repository)

[← Wiki Home](Home.md)

Executable procedures live in the **main repository** (not duplicated on the GitHub Wiki mirror).

| Runbook | Path in repo |
|---------|----------------|
| Index | `docs/runbooks/README.md` |
| CI parity (local / VPS) | `docs/runbooks/ci-parity-local.md` |
| Pre-release gate | `docs/runbooks/pre-release-gate.md` |
| Compose smoke (CI mirror) | `docs/runbooks/compose-smoke-ci.md` |

Quick command (from a clone):

```bash
./scripts/runbooks/ci-parity.sh ci
```
