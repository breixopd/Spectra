# Operations

[← Wiki Home](home.md) | [Deployment Guide](deployment-guide.md) | [Scaling](scaling.md) | [Worker System](worker-system.md) | [Testing Strategy](testing-strategy.md)

---

Canonical operator-facing runbook index for day-2 work. Use this page for health triage, backup and restore entry points, queue recovery, user and session response, logging, and deploy or rollback references.

## Operator Entry Points

| Audience | Primary doc | Use this for |
|----------|-------------|--------------|
| Operators and on-call responders | [Operations](operations.md) | Day-2 checks, incidents, repair work, and script entry points |
| Script users working from the repo | [scripts/ops/README.md](../../scripts/ops/README.md) | Local script catalog with safety labels and common commands |
| Platform owners and deployers | [Deployment Guide](deployment-guide.md) | Bootstrap, Compose or Swarm rollout, host prerequisites, and first deploy |
| Developers | [Development](development.md) | Local workflow, tests, and contributing |
| Release and verification owners | [Testing Strategy](testing-strategy.md) | Platform-wide validation matrix, release gate, and known gaps |

## Health And Triage Flow

| Step | Read-only checks first | Escalate with |
|------|------------------------|---------------|
| 1. Confirm reachability | `./scripts/health_check.sh http://<host>/api/health` | Set `HEALTH_CHECK_FULL=1` for deeper worker and storage checks |
| 2. Inspect service behavior | `scripts/ops/log_management.sh errors [service]` or `tail [service]` | `scripts/ops/log_management.sh export <dir>` for incident capture |
| 3. Check queue and worker state | `scripts/ops/worker_management.sh status`, `failed`, `dead-letter`, `worker-health` | `retry-failed`, `retry-job <id>`, or purge commands after review |
| 4. Check storage and backups | `scripts/ops/s3_management.sh health`, `status`, `usage`; `scripts/ops/backup_restore.sh list`, `verify <backup_id>` | `create-buckets`, `create`, or `restore <backup_id>` when change control allows |
| 5. Check database pressure | `scripts/ops/db_maintenance.sh stats` and `sizes` | `vacuum`, `analyze`, or `reindex` during maintenance windows |

## Runbook Entry Points

### Backup, Restore, And Disaster Recovery

| Entry point | What it covers | Safety |
|-------------|----------------|--------|
| `scripts/ops/backup_restore.sh list` and `verify <backup_id>` | Inspect available S3-native backups before making changes | Read-only |
| `scripts/ops/backup_restore.sh create` | Operator-driven backup outside the scheduler cadence | Mutating |
| `scripts/ops/backup_restore.sh restore <backup_id>` | Restore the database from an S3 backup after explicit confirmation | Destructive and confirmation-required |
| [Deployment Guide](deployment-guide.md) | Runtime storage requirements, bootstrap, and post-deploy verification | Reference |
| [Deployment](deployment.md#rollback) | Version rollback mechanics and database downgrade path | Reference |

- Automated backups are created by the scheduler when `BACKUP_ENABLED=true`.
- Backups are stored in `S3_BUCKET_BACKUPS`; there is no local filesystem fallback.

### Queue And Worker Recovery

| Entry point | What it covers | Safety |
|-------------|----------------|--------|
| `scripts/ops/worker_management.sh status`, `pending`, `failed`, `dead-letter`, `worker-health` | Queue visibility, failed-job review, and worker reachability | Read-only |
| `scripts/ops/worker_management.sh retry-failed` and `retry-job <id>` | Requeue work after operator review | Mutating |
| `scripts/ops/worker_management.sh purge-completed` and `purge-dead` | Remove historical queue records | Destructive |
| [Worker System](worker-system.md) | Queue lifecycle, retry behavior, cleanup loops, and job types | Reference |

### User, Session, And Mission Incidents

| Entry point | What it covers | Safety |
|-------------|----------------|--------|
| `scripts/ops/incident_response.sh audit-recent [minutes]` and `active-sessions` | Review recent audit entries and currently valid sessions | Read-only |
| `scripts/ops/incident_response.sh invalidate-user`, `lock-user`, `kill-mission <id>`, `unlock-user` | Targeted account or mission response | Mutating |
| `scripts/ops/incident_response.sh invalidate-all-sessions`, `kill-missions`, `lockdown`, `lift-lockdown` | Broad emergency response actions | Destructive |
| `scripts/ops/user_management.sh list` and `info <username>` | Inspect account state before changing it | Read-only |
| `scripts/ops/user_management.sh create-admin`, `set-role`, `reset-password`, `disable-mfa` | Administrative account recovery and access repair | Mutating |
| `scripts/ops/user_management.sh delete <username>` | Permanently remove a user after explicit confirmation | Destructive and confirmation-required |

### Storage, Logging, And Platform Visibility

| Entry point | What it covers | Safety |
|-------------|----------------|--------|
| `scripts/ops/s3_management.sh status`, `buckets`, `list`, `usage`, `health` | Garage or S3 visibility, object inspection, and storage health | Read-only |
| `scripts/ops/s3_management.sh create-buckets` | Create the required Spectra buckets | Mutating |
| `scripts/ops/log_management.sh tail`, `errors`, `sizes`, `export` | Service logs, recent errors, and capture for incident review | Read-only |
| [Scaling](scaling.md) | Storage topology, bucket contract, and distributed deployment patterns | Reference |

## Safety Model

| Safety level | Default use | Examples |
|--------------|-------------|----------|
| Read-only | Start here during triage | `scripts/health_check.sh`, `log_management.sh errors`, `db_maintenance.sh stats`, `worker_management.sh status`, `s3_management.sh health`, `backup_restore.sh list`, `incident_response.sh audit-recent`, `user_management.sh info` |
| Mutating | Use after diagnosis and with an operator note or ticket | `backup_restore.sh create`, `db_maintenance.sh vacuum`, `s3_management.sh create-buckets`, `worker_management.sh retry-job`, `user_management.sh reset-password`, `incident_response.sh lock-user` |
| Destructive | Use only with explicit approval and rollback context | `backup_restore.sh restore`, `worker_management.sh purge-dead`, `incident_response.sh lockdown`, `incident_response.sh kill-missions`, `user_management.sh delete` |

Some destructive commands prompt for confirmation, but not all disruptive actions do. Treat the label as an operational guardrail rather than a guarantee of an interactive prompt.

## Related References

- For the full local script inventory, see [scripts/ops/README.md](../../scripts/ops/README.md).
- For deployment and bootstrap steps, see [Deployment Guide](deployment-guide.md).
- For CI/CD versioning and rollback mechanics, see [Deployment](deployment.md).
- For queue internals, see [Worker System](worker-system.md).
- For the platform-wide testing strategy, see [Testing Strategy](testing-strategy.md).

---

## Automated Maintenance (Scheduler)

The scheduler service handles most recurring maintenance automatically. These tasks run on configurable intervals and use PostgreSQL advisory locks for safe multi-replica operation.

| Task | Interval | What It Does |
|------|----------|--------------|
| Sandbox watchdog | 60s | Detects and cleans up stale sandbox containers |
| Warm pool maintenance | Continuous | Maintains `SANDBOX_WARM_POOL_SIZE` pre-warmed containers |
| Quota reset | Daily at midnight UTC | Resets daily API usage counters |
| Metrics collection | 30s | Collects and aggregates system metrics |
| Backup scheduler | `BACKUP_SCHEDULE_HOURS` | Creates S3-native database backups |
| Cache cleanup | 10 min | Purges expired cache entries |
| Periodic cleanup | 1 hour | Cleans completed/dead-letter jobs (>30 days), orphaned sandboxes |
| DB maintenance | `DB_MAINTENANCE_INTERVAL` (7 days) | VACUUM ANALYZE on key tables |
| Stale job recovery | `STALE_JOB_RECOVERY_INTERVAL` (5 min) | Recovers jobs stuck in `in_progress` for >30 min |
| Exploit DB refresh | `EXPLOIT_DB_REFRESH_HOURS` (168h) | Updates exploit database indexes |
| Docker cleanup | `DOCKER_CLEANUP_INTERVAL` (7 days) | Prunes exited containers, dangling images, orphaned volumes |
| Disk monitor | Periodic | Monitors disk usage and warns on low space |
| Capacity monitor | 60s | Tracks server pool utilization, drives auto-scaling |

Manual scripts under `scripts/ops/` are still available for on-demand operations but are no longer the primary mechanism for recurring tasks.

---

## Auto-Scaling Management

When `AUTOSCALE_ENABLED=true`, the scheduler's capacity monitor automatically adjusts replica counts. See [Scaling](scaling.md#auto-scaling) for configuration and policy details.

To monitor auto-scaling activity:

```bash
# Check scheduler logs for scaling events
docker compose -f docker/docker-compose.yml logs scheduler | grep -i "scale"
```

Capacity alerts (80% warning, 100% critical) are sent via `NOTIFICATION_WEBHOOK` regardless of whether auto-scaling is enabled.

---

## GDPR Data Management

Spectra provides GDPR-compliant data management features accessible via API and UI.

### User Data Export (Article 20)

Users can export all their data from the Settings → Data & Privacy tab, or via API:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5000/api/v1/auth/export-data \
  -o spectra-data-export.json
```

The export includes: user profile, missions, targets, findings, and audit log entries.

### Restrict Processing (Article 18)

Users can toggle a processing restriction flag on their account:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"restricted": true}' \
  http://localhost:5000/api/v1/auth/restrict-processing
```

### Account Deletion (Article 17)

Users can permanently delete their account and all associated data. Requires password confirmation. Audit logs are preserved with `user_id` set to NULL.

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password": "current-password"}' \
  http://localhost:5000/api/v1/auth/account
```

The last superuser account cannot be deleted.
