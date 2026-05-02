# Scripts layout

Run everything from the **repository root** unless a script says otherwise.

| Area | Path | Role |
|------|------|------|
| **CI / verification** | [`runbooks/ci-parity.sh`](runbooks/ci-parity.sh) | Mirror GitHub Actions: static analysis, unit coverage ≥70%, settings; `all` adds integration. |
| **Extended matrix** | [`runbooks/full-test-matrix.sh`](runbooks/full-test-matrix.sh) | Parity + load/perf/soak + Playwright + live targets + optional LLM live + API e2e (`SKIP_*` in header). |
| **VPS sync** | [`runbooks/vps-sync.sh`](runbooks/vps-sync.sh) | `rsync` to server; **excludes `.env.test`** so remote secrets survive. |
| **Daily tests** | [`test.sh`](test.sh) | Docker pytest helpers (`unit`, `integration`, `live-smoke`, …). |
| **Quick unit (wrapper)** | [`ops/run_unit_tests_docker.sh`](ops/run_unit_tests_docker.sh) | Delegates to `runbooks/ci-parity.sh unit`. |
| **Deploy / rollback** | [`deploy.sh`](deploy.sh), [`rollback.sh`](rollback.sh) | Production workflows; uses [`health_check.sh`](health_check.sh). |
| **Bootstrap** | [`first_run.sh`](first_run.sh), [`start.sh`](start.sh) | Local/setup and container entry helpers. |
| **Imports / codegen** | [`check_import_boundaries.py`](check_import_boundaries.py), [`update_imports.py`](update_imports.py) | Package boundary checks and refactors. |
| **Smoke** | [`live_smoke.py`](live_smoke.py) | API/UI/LLM smoke against a running stack. |
| **Version** | [`version.py`](version.py) | Version helper for builds. |
| **Operations** | [`ops/`](ops/README.md) | Incident response, S3/Garage, workers, logs, swarm, hardening — see ops README. |

Canonical documentation: [docs/runbooks/README.md](../docs/runbooks/README.md), [docs/wiki/operations.md](../docs/wiki/operations.md).
