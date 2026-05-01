# Operations Scripts

Run these helper scripts from the repository root against the standard `spectra-*` container names unless you override the related environment variables.

The canonical operator workflow lives in [../../docs/wiki/operations.md](../../docs/wiki/operations.md). The sibling health probe lives at [../health_check.sh](../health_check.sh).

**CI / release verification:** [../../docs/runbooks/README.md](../../docs/runbooks/README.md) — run `./scripts/runbooks/ci-parity.sh ci` from repo root for the same gates as GitHub Actions (Docker).

| Script | Purpose | Common entry points | Safety label | Status |
|--------|---------|---------------------|--------------|--------|
| `golden_image_refresh.sh` | Refresh golden VM/container images | — | Mutating | Active |
| `harden_server.sh` | Apply server hardening baseline | — | Mutating | Active |
| `incident_response.sh` | Handle session, user, mission, and lockdown incidents | `audit-recent`, `active-sessions`, `invalidate-user`, `kill-mission`, `lockdown` | Destructive | Active |
| `log_management.sh` | Inspect and export service logs | `tail [service]`, `errors [service]`, `sizes`, `export <dir>` | Read-only | Active |
| `migrate_server.sh` | Migrate services between servers | — | Mutating | Active |
| `s3_management.sh` | Inspect Garage or S3 state and create required buckets | `status`, `buckets`, `list <bucket>`, `usage`, `create-buckets`, `health` | Mutating | Active |
| `swarm_deploy.sh` | Deploy or update the Swarm stack | — | Mutating | Active |
| `worker_management.sh` | Inspect, retry, and purge queue work | `status`, `failed`, `dead-letter`, `retry-job <id>`, `purge-completed`, `purge-dead`, `worker-health` | Destructive | Active — Admin UI planned |

## Safety Notes

- Start with the read-only commands in each script before running mutating or destructive actions.
- `worker_management.sh` purge commands and several `incident_response.sh` actions are immediately disruptive even though they do not prompt.
