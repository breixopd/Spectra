#!/usr/bin/env bash
# Worker Queue Management
# Usage: ./scripts/ops/worker_management.sh <command>
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-spectra-db}"
DB_USER="${DB_USER:-spectra}"
DB_NAME="${DB_NAME:-spectra}"
WORKER_CONTAINER="${WORKER_CONTAINER:-spectra-worker}"

run_sql() {
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "$1"
}

usage() {
    cat <<EOF
Spectra Worker Queue Management

Usage: $0 <command>

Commands:
  status           Show queue statistics (pending, running, failed, dead-letter)
  pending          List pending jobs
  failed           List recently failed jobs
  dead-letter      List dead-letter (permanently failed) jobs
  retry-failed     Move failed jobs back to pending
  retry-job <id>   Retry a specific failed job
  purge-completed  Delete completed jobs (older than 24h)
  purge-dead       Delete all dead-letter jobs
  worker-health    Check worker container health
EOF
}

case "${1:-}" in
    status)
        echo "=== Job Queue Statistics ==="
        run_sql "SELECT status, COUNT(*) as count FROM job_queue GROUP BY status ORDER BY status;"
        echo ""
        echo "Jobs by type:"
        run_sql "SELECT queue_name, function AS job_type, status, COUNT(*) FROM job_queue GROUP BY queue_name, function, status ORDER BY queue_name, function, status;"
        ;;
    pending)
        run_sql "SELECT id, queue_name, function AS job_type, status, enqueued_at, priority FROM job_queue WHERE status IN ('queued', 'pending') ORDER BY priority DESC, enqueued_at LIMIT 50;"
        ;;
    failed)
        run_sql "SELECT id, queue_name, function AS job_type, error AS error_message, COALESCE(completed_at, started_at, enqueued_at) AS last_updated_at, retry_count, max_retries FROM job_queue WHERE status = 'failed' ORDER BY COALESCE(completed_at, started_at, enqueued_at) DESC LIMIT 50;"
        ;;
    dead-letter)
        run_sql "SELECT id, queue_name, function AS job_type, error AS error_message, enqueued_at, completed_at, retry_count, max_retries FROM job_queue WHERE status = 'dead_letter' ORDER BY COALESCE(completed_at, started_at, enqueued_at) DESC LIMIT 50;"
        ;;
    retry-failed)
        echo "Moving all failed jobs back to pending..."
        run_sql "UPDATE job_queue SET status = 'pending', error = NULL, started_at = NULL, completed_at = NULL, retry_count = retry_count + 1 WHERE status = 'failed';"
        echo "Done."
        ;;
    retry-job)
        [[ -z "${2:-}" ]] && echo "Usage: $0 retry-job <job-id>" && exit 1
        run_sql "UPDATE job_queue SET status = 'pending', error = NULL, started_at = NULL, completed_at = NULL WHERE id = '$2';"
        echo "Job $2 moved to pending."
        ;;
    purge-completed)
        echo "Purging completed jobs older than 24 hours..."
        run_sql "DELETE FROM job_queue WHERE status = 'completed' AND completed_at < NOW() - INTERVAL '24 hours';"
        echo "Done."
        ;;
    purge-dead)
        echo "Purging all dead-letter jobs..."
        run_sql "DELETE FROM job_queue WHERE status = 'dead_letter';"
        echo "Done."
        ;;
    worker-health)
        echo "Worker container status:"
        docker inspect --format='{{.State.Status}} (health: {{.State.Health.Status}})' "${WORKER_CONTAINER}" 2>/dev/null || echo "Worker container not found"
        echo ""
        echo "Worker process list:"
        docker exec "${WORKER_CONTAINER}" ps aux 2>/dev/null || echo "Cannot reach worker container"
        ;;
    *)
        usage
        ;;
esac
