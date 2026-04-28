# Worker & Background Task System

[← Wiki Home](home.md) | [Operations](operations.md) | [Architecture](architecture.md) | [Configuration](configuration.md)

---

Spectra uses a PostgreSQL-backed job queue for background task processing. Workers run inside the tools container and handle tool execution, cleanup, notifications, and report generation.

### Tools Container

The tools container (`Dockerfile.tools`) is a minimal Kali Linux image (~1.1 GB) with Python, networking utilities, and VPN support. **Security tools are not preinstalled** — they are installed on demand from the plugin registry (`plugins/*.json`) when first needed.

On startup, the worker:

1. Initializes the tool plugin registry
2. Auto-installs any pending tools (unless `WORKER_SKIP_STARTUP_AUTO_INSTALL=true`)
3. Starts a heartbeat loop (for sandbox workers)
4. Enters the main `worker_loop` — polling for and executing jobs

This on-demand approach keeps the base image small and ensures tools match plugin configurations. When plugins are updated via the API, a `PLUGIN_UPDATED` event triggers a golden image rebuild (always-on platform behaviour).

The queue is implemented in `app/core/queue.py` using the `job_queue` database table. Jobs are claimed via `SELECT ... FOR UPDATE SKIP LOCKED` for safe concurrent processing.

### Job Lifecycle

```
pending → in_progress → completed
                      → failed → pending (retry)
                               → dead_letter (max retries exceeded)
```

Each job has:

| Field | Type | Description |
|-------|------|-------------|
| `queue_name` | string | Queue partition (e.g. `default`, sandbox ID) |
| `function_name` | string | Python function to invoke |
| `args` | JSON | Serialized arguments |
| `status` | string | `pending`, `in_progress`, `completed`, `failed`, `dead_letter` |
| `priority` | int | Lower = higher priority (default 5) |
| `retry_count` | int | Current retry attempt |
| `max_retries` | int | Maximum retries before dead letter (default 3) |
| `timeout` | int | Job timeout in seconds |

### Worker Entry Point

The worker runs `uvicorn spectra_worker.main:app` inside the tools container. See "Tools Container" above for the startup sequence.

---

## Dead-Letter Queue

When a job fails, it is retried up to `max_retries` times (default 3). After exhausting retries, the job moves to `dead_letter` status with the error message preserved.

### Retry Behavior

1. Job fails → `retry_count` incremented
2. If `retry_count < max_retries` → status reset to `pending` for re-execution
3. If `retry_count >= max_retries` → status set to `dead_letter`, `completed_at` timestamped

### Monitoring Dead-Letter Jobs

Dead-letter jobs can be listed programmatically via `PostgresJobQueue.list_dead_letter_jobs(limit=50)`. This returns all `dead_letter` jobs for the queue, ordered by `completed_at` descending.

```python
from app.infrastructure.queue import PostgresJobQueue

queue = PostgresJobQueue("default")
dead_jobs = await queue.list_dead_letter_jobs(limit=50)
for job in dead_jobs:
    print(f"{job.id}: {job.function_name} — {job.error}")
```

Dead-letter jobs older than 30 days are automatically purged by the cleanup system (see below).

---

## Cleanup Jobs

Periodic cleanup runs every **hour** via `periodic_cleanup_loop()` in the application lifespan (`app/core/lifespan.py`). It calls `run_all_cleanup()` which executes four tasks:

| Task | Function | Description |
|------|----------|-------------|
| Expired cache | `cleanup_expired_cache` | Removes `system_cache` entries past their `expires_at` |
| Old cache entries | `cleanup_old_cache_entries` | Purges `cache_entries` older than 7 days |
| Completed jobs | `cleanup_completed_jobs` | Deletes `completed` and `dead_letter` jobs older than 30 days |
| Orphaned sandboxes | `cleanup_orphaned_sandboxes` | Finds and destroys sandbox containers that escaped normal cleanup |

Additionally, a separate **cache cleanup loop** runs every 10 minutes to purge expired in-memory cache entries.

### Sandbox Watchdog

A dedicated watchdog loop runs every 60 seconds to check sandbox heartbeats. Sandboxes that exceed `SANDBOX_IDLE_TIMEOUT` without a heartbeat are reaped automatically.

---

## Notification Jobs

Background notification delivery for mission events. Notifications are sent via webhook (ntfy.sh, Slack, Discord, or any HTTP endpoint).

| Job | Trigger | Description |
|-----|---------|-------------|
| `send_webhook_notification` | Generic | POST JSON payload to a webhook URL |
| `send_mission_completion_notification` | Mission completes | Notifies with finding count and critical count |
| `send_critical_finding_alert` | Critical/high finding | Urgent alert with finding title and description |

### Webhook Security

All webhook URLs are validated against SSRF before delivery:
- Only `http`/`https` schemes allowed
- Private, loopback, link-local, and reserved IPs are blocked
- DNS resolution is checked to prevent DNS rebinding

Configure the webhook endpoint via the `NOTIFICATION_WEBHOOK` environment variable.

---

## Report Generation Jobs

Background report generation using the Reporter AI agent.

| Job | Description |
|-----|-------------|
| `generate_mission_report` | Full mission report (PDF/HTML) with findings, severity charts, MITRE ATT&CK mapping |
| `generate_executive_summary` | Concise executive summary for stakeholders |

Reports are generated by invoking the `ReporterAgent` with mission data and findings, then stored in the mission object-storage bucket via the S3-backed storage service.

---

## Queue Operations CLI

Use [Operations](operations.md) for the canonical queue-recovery workflow and [scripts/ops/README.md](../../scripts/ops/README.md) for the local script index. This page stays focused on queue architecture, retry behavior, cleanup loops, and job types.

---

## Job Types Reference

All registered worker functions:

| Category | Functions |
|----------|-----------|
| **Tool ops** | `execute_tool_job`, `install_tool_job`, `uninstall_tool_job`, `install_all_tools_job`, `reload_plugins_job`, `get_tool_status_job`, `sync_all_status_job` |
| **Commands** | `run_command_job`, `execute_script_job` |
| **VPN** | `vpn_connect_job`, `vpn_disconnect_job`, `vpn_status_job`, `vpn_test_job` |
| **Cleanup** | `run_all_cleanup` |
| **Notifications** | `send_webhook_notification`, `send_mission_completion_notification`, `send_critical_finding_alert` |
| **Reports** | `generate_mission_report`, `generate_executive_summary` |
