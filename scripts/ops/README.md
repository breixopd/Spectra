# Operations Scripts

Run these helper scripts from the repository root against the standard `spectra-*` container names unless you override the related environment variables.

The canonical operator workflow lives in [../../docs/wiki/operations.md](../../docs/wiki/operations.md). The sibling health probe lives at [../health_check.sh](../health_check.sh).

| Script | Purpose | Common entry points | Safety label |
|--------|---------|---------------------|--------------|
| `backup_restore.sh` | Manage S3-native database backups | `list`, `verify <backup_id>`, `create`, `restore <backup_id>` | Destructive and confirmation-required |
| `db_maintenance.sh` | Inspect PostgreSQL activity and run maintenance | `stats`, `sizes`, `vacuum`, `analyze`, `reindex` | Mutating |
| `incident_response.sh` | Handle session, user, mission, and lockdown incidents | `audit-recent`, `active-sessions`, `invalidate-user`, `kill-mission`, `lockdown` | Destructive |
| `log_management.sh` | Inspect and export service logs | `tail [service]`, `errors [service]`, `sizes`, `export <dir>` | Read-only |
| `s3_management.sh` | Inspect Garage or S3 state and create required buckets | `status`, `buckets`, `list <bucket>`, `usage`, `create-buckets`, `health` | Mutating |
| `user_management.sh` | Inspect and administer user accounts | `list`, `info <username>`, `create-admin`, `set-role`, `reset-password`, `disable-mfa`, `delete <username>` | Destructive and confirmation-required |
| `worker_management.sh` | Inspect, retry, and purge queue work | `status`, `failed`, `dead-letter`, `retry-job <id>`, `purge-completed`, `purge-dead`, `worker-health` | Destructive |

## Safety Notes

- Start with the read-only commands in each script before running mutating or destructive actions.
- `backup_restore.sh restore <backup_id>` and `user_management.sh delete <username>` prompt for confirmation.
- `worker_management.sh` purge commands and several `incident_response.sh` actions are immediately disruptive even though they do not prompt.
