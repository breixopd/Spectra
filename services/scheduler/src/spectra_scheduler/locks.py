"""Advisory lock IDs and background task naming for scheduler coordination."""

from app.auth.advisory_locks import stable_lock_id

# Stable advisory lock IDs for inter-replica coordination (PostgreSQL pg_advisory_lock)
_BACKUP_LOCK_ID: int = stable_lock_id("spectra_backup")
_QUOTA_LOCK_ID: int = stable_lock_id("spectra_quota_reset")
_DB_MAINTENANCE_LOCK_ID: int = stable_lock_id("spectra_db_maint")
_EXPLOIT_REFRESH_LOCK_ID: int = stable_lock_id("spectra_exploit_refresh")
_STALE_JOB_LOCK_ID: int = stable_lock_id("spectra_stale_jobs")
_DOCKER_CLEANUP_LOCK_ID: int = stable_lock_id("spectra_docker_cleanup")
_IMAGE_UPDATE_LOCK_ID: int = stable_lock_id("spectra_image_update")
_SANDBOX_WATCHDOG_LOCK_ID: int = stable_lock_id("spectra_sandbox_watchdog")
_METRICS_COLLECTOR_LOCK_ID: int = stable_lock_id("spectra_metrics_collector")
_HEALTH_REPORTER_LOCK_ID: int = stable_lock_id("spectra_health_reporter")
_CACHE_CLEANUP_LOCK_ID: int = stable_lock_id("spectra_cache_cleanup")
_PERIODIC_CLEANUP_LOCK_ID: int = stable_lock_id("spectra_periodic_cleanup")
_CAPACITY_MONITOR_LOCK_ID: int = stable_lock_id("spectra_capacity_monitor")
_DISK_MONITOR_LOCK_ID: int = stable_lock_id("spectra_disk_monitor")
_INFRA_MONITOR_LOCK_ID: int = stable_lock_id("spectra_infrastructure_monitor")
_SCHEDULER_LEADER_LOCK_ID: int = stable_lock_id("spectra_scheduler_leader")

_SCHEDULER_TASK_SPECS: tuple[tuple[str, str], ...] = (
    ("sandbox_watchdog", "_sandbox_watchdog"),
    ("quota_reset", "_quota_reset"),
    ("metrics_collector", "_metrics_collector"),
    ("health_reporter", "_health_reporter"),
    ("backup_scheduler", "_backup_scheduler"),
    ("cache_cleanup", "_cache_cleanup"),
    ("periodic_cleanup", "_periodic_cleanup"),
    ("db_maintenance", "_db_maintenance"),
    ("stale_job_recovery", "_stale_job_recovery"),
    ("exploit_db_refresh", "_exploit_db_refresh"),
    ("capacity_monitor", "_capacity_monitor"),
    ("infrastructure_monitor", "_infrastructure_monitor"),
    ("docker_cleanup", "_docker_cleanup"),
    ("disk_monitor", "_disk_monitor"),
    ("image_update_check", "_image_update_check"),
)
