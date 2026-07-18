# Operations Scripts

Run these helper scripts from the repository root against the standard `spectra-*` container names unless you override the related environment variables.

The canonical operator workflow lives in [../../docs/wiki/operations.md](../../docs/wiki/operations.md). The sibling health probe lives at [../health_check.sh](../health_check.sh).

**Scripts map:** [../README.md](../README.md) (runbooks vs ops vs wrappers).

**CI / release verification:** [../../docs/runbooks/README.md](../../docs/runbooks/README.md) — from repo root, `./scripts/runbooks/ci-parity.sh ci` runs the core Docker merge gate (**`static-analysis`** + **`test`** slices: static checks, unit coverage ≥65% across all first-party packages, settings). It does not replace CI **`deps`**, **`docker-build`**, or push-only **`compose-smoke`**; see [CI parity](../../docs/runbooks/ci-parity-local.md).

**Unit-only on a VM:** `scripts/ops/vps-verify-tests.sh` and `scripts/ops/run_unit_tests_docker.sh` both delegate to `scripts/runbooks/ci-parity.sh unit` (avoid duplicated compose commands).

| Script | Purpose | Common entry points | Safety label | Status |
|--------|---------|---------------------|--------------|--------|
| **Golden image build (Python CLI)** | Build + validate + scan + push the golden tools image | `uv run python -m spectra_tools.sandbox.golden_image` (`--print-dockerfile` to inspect) | Mutating | Active |
| `harden_server.sh` | Apply server hardening baseline | — | Mutating | Active |
| `incident_response.sh` | Handle session, user, mission, and lockdown incidents | `audit-recent`, `active-sessions`, `invalidate-user`, `kill-mission`, `lockdown` | Destructive | Active |
| `log_management.sh` | Inspect and export service logs | `tail [service]`, `errors [service]`, `sizes`, `export <dir>` | Read-only | Active |
| `migrate_server.sh` | Migrate services between servers | — | Mutating | Active |
| `s3_management.sh` | Inspect Garage or S3 state and create required buckets | `status`, `buckets`, `list <bucket>`, `usage`, `create-buckets`, `health` | Mutating | Active |
| `swarm_deploy.sh` | Deploy or update the Swarm stack | — | Mutating | Active |
| `worker_management.sh` | Inspect, retry, and purge queue work | `status`, `failed`, `dead-letter`, `retry-job <id>`, `purge-completed`, `purge-dead`, `worker-health` | Destructive | Active |
| `host-maintenance.sh` | Journal vacuum, configured logrotate policy, managed Docker builder/container/image prune | `sudo ./scripts/ops/host-maintenance.sh` (`AGGRESSIVE=1` for stronger image prune) | Mutating | Active |
| `suggest-compose-scale.sh` | Print suggested `AUTOSCALE_*` caps from CPU/RAM | `./scripts/ops/suggest-compose-scale.sh` | Read-only | Active |
| **Python host ops (scheduler image)** | `python -m spectra_scaling.runtime.host_ops_cli` | One-shot Docker prune; used by systemd on pool hosts after provision | Mutating | Active |

## Safety Notes

- Start with the read-only commands in each script before running mutating or destructive actions.
- `worker_management.sh` purge commands and several `incident_response.sh` actions are immediately disruptive even though they do not prompt.
