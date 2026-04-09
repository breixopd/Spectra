#!/bin/bash
# Spectra Production Deploy Script
# Usage: ./scripts/deploy.sh [version]
# Environment: DEPLOY_WEBHOOK_URL, COMPOSE_FILE, DATABASE_URL
#
# Features:
#   - Lock file to prevent concurrent deploys
#   - Pre-deploy health check against current running version
#   - Database backup via pg_dump before migration
#   - In-place rolling restart: pull new images, restart containers, health check
#   - Post-deploy health check with exponential backoff
#   - Automatic rollback on failure
#   - Deploy notification via webhooks (optional)
#   - Logging to logs/deploy.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HEALTH_CHECK="$SCRIPT_DIR/health_check.sh"
LOCK_FILE="/tmp/spectra-deploy.lock"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/deploy.log"
BACKUP_DIR="$PROJECT_DIR/data/backups"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_DIR/docker/docker-compose.yml}"
HEALTH_URL="${HEALTH_URL:-http://localhost:80/api/health}"
VERSION="${1:-latest}"
DEPLOY_WEBHOOK_URL="${DEPLOY_WEBHOOK_URL:-}"
OLD_CONTAINER=""
NEW_CONTAINER=""
DB_BACKUP_FILE=""

# ── Helpers ──────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $(basename "$0") [version]

Arguments:
  version   Docker image version tag to deploy (default: latest)

Environment variables:
  COMPOSE_FILE        Docker compose file (default: docker/docker-compose.yml)
  DEPLOY_WEBHOOK_URL  Webhook URL for deploy notifications (optional)
  HEALTH_URL          Health check URL (default: http://localhost:80/api/health)
  DATABASE_URL        PostgreSQL connection URL (for pg_dump)

Examples:
  $(basename "$0") 2026.03.12
  DEPLOY_WEBHOOK_URL=https://hooks.slack.com/... $(basename "$0") latest
EOF
    exit 0
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
fi

mkdir -p "$LOG_DIR" "$BACKUP_DIR"

log() {
    local msg
    msg="[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

notify() {
    local status="$1" message="$2"
    if [ -n "$DEPLOY_WEBHOOK_URL" ]; then
        local payload
        payload=$(python3 -c "import json,sys; print(json.dumps({'text': '[Spectra Deploy] ' + sys.argv[1] + ': ' + sys.argv[2] + ' (version: ' + sys.argv[3] + ')'}))" "$status" "$message" "$VERSION")
        curl -sf --max-time 10 -X POST -H 'Content-Type: application/json' \
            -d "$payload" "$DEPLOY_WEBHOOK_URL" > /dev/null 2>&1 || true
    fi
}

cleanup_lock() {
    # flock is released automatically when fd 9 is closed (process exit)
    rm -f "$LOCK_FILE"
}

# ── Signal handling ──────────────────────────────────────────────

on_exit() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log "ERROR: Deploy interrupted or failed (exit code: $exit_code)"
        notify "FAILED" "Deploy interrupted (exit $exit_code)"
        rollback
    fi
    cleanup_lock
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ── Lock ─────────────────────────────────────────────────────────

acquire_lock() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        log "ERROR: Another deploy is running"
        # Exit without triggering rollback—we never started
        trap - EXIT
        exit 1
    fi
    log "Lock acquired (PID: $$)"
}

# ── Database backup ──────────────────────────────────────────────

backup_database() {
    log "Backing up database..."
    DB_BACKUP_FILE="$BACKUP_DIR/spectra_pre_deploy_$(date -u '+%Y%m%d_%H%M%S').sql.gz"

    if docker exec spectra-db pg_dump -U spectra -d spectra 2>/dev/null | gzip > "$DB_BACKUP_FILE"; then
        local size
        size=$(du -h "$DB_BACKUP_FILE" | cut -f1)
        log "Database backup complete: $DB_BACKUP_FILE ($size)"
    else
        log "WARN: Database backup failed — container may not be running. Continuing..."
        DB_BACKUP_FILE=""
    fi
}

# ── Rollback ─────────────────────────────────────────────────────

rollback() {
    log "Starting rollback..."
    notify "ROLLING_BACK" "Attempting rollback"

    # Stop new containers if they exist
    if [ -n "$NEW_CONTAINER" ] && docker ps -q -f "name=$NEW_CONTAINER" 2>/dev/null | grep -q .; then
        log "Stopping new container: $NEW_CONTAINER"
        docker stop "$NEW_CONTAINER" 2>/dev/null || true
        docker rm "$NEW_CONTAINER" 2>/dev/null || true
    fi

    # Restart old containers
    log "Restarting previous deployment..."
    VERSION="${OLD_VERSION:-latest}" docker compose -f "$COMPOSE_FILE" up -d --remove-orphans 2>/dev/null || true

    # Restore DB if backup exists and migration may have run
    if [ -n "$DB_BACKUP_FILE" ] && [ -f "$DB_BACKUP_FILE" ]; then
        log "Restoring database from backup: $DB_BACKUP_FILE"
        if gunzip -c "$DB_BACKUP_FILE" | docker exec -i spectra-db psql --set ON_ERROR_STOP=1 -U spectra -d spectra; then
            log "Database restored successfully"
        else
            log "ERROR: Database restore failed — manual intervention required"
        fi
    fi

    # Verify rollback
    if bash "$HEALTH_CHECK" "$HEALTH_URL" 3 5 2>/dev/null; then
        log "Rollback successful"
        notify "ROLLED_BACK" "Rollback completed successfully"
    else
        log "ERROR: Rollback health check failed — manual intervention required"
        notify "CRITICAL" "Rollback failed — manual intervention required"
    fi
}

# ── Pre-deploy checks ───────────────────────────────────────────

pre_deploy_check() {
    log "Running pre-deploy checks..."

    # Check docker is available
    if ! docker info > /dev/null 2>&1; then
        log "ERROR: Docker is not running"
        exit 1
    fi

    # Check compose file exists
    if [ ! -f "$COMPOSE_FILE" ]; then
        log "ERROR: Compose file not found: $COMPOSE_FILE"
        exit 1
    fi

    # Check health_check script exists
    if [ ! -x "$HEALTH_CHECK" ]; then
        log "ERROR: Health check script not found or not executable: $HEALTH_CHECK"
        exit 1
    fi

    # Record current running version for rollback
    OLD_VERSION=$(docker inspect --format='{{ index .Config.Labels "org.opencontainers.image.version" }}' spectra-app 2>/dev/null || echo "latest")
    log "Current running version: $OLD_VERSION"

    # Check current deployment health (non-fatal — may be first deploy)
    if docker ps -q -f "name=spectra-app" 2>/dev/null | grep -q .; then
        if bash "$HEALTH_CHECK" "$HEALTH_URL" 2 3 2>/dev/null; then
            log "Current deployment is healthy"
        else
            log "WARN: Current deployment is unhealthy — proceeding anyway"
        fi
    else
        log "No existing deployment found — fresh deploy"
    fi
}

# ── Deploy ───────────────────────────────────────────────────────

deploy() {
    log "Deploying version: $VERSION"
    notify "DEPLOYING" "Starting deploy"

    # Pull new images
    log "Pulling images for version: $VERSION"
    VERSION="$VERSION" docker compose -f "$COMPOSE_FILE" pull

    # In-place restart: pull new images and recreate containers
    log "Starting new containers..."
    VERSION="$VERSION" docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

    # Post-deploy health check with exponential backoff
    log "Running post-deploy health check..."
    if bash "$HEALTH_CHECK" "$HEALTH_URL" 5 3; then
        log "Deploy successful: version $VERSION is healthy"
        notify "SUCCESS" "Deploy completed — version $VERSION is live"
    else
        log "ERROR: Post-deploy health check failed"
        notify "FAILED" "Post-deploy health check failed"
        return 1
    fi

    # Clean up old images
    log "Pruning old images..."
    docker image prune -f --filter "until=24h" > /dev/null 2>&1 || true

    # Clean up old backups (keep last 10)
    if [ -d "$BACKUP_DIR" ]; then
        local count
        count=$(find "$BACKUP_DIR" -name "spectra_pre_deploy_*.sql.gz" -type f | wc -l)
        if [ "$count" -gt 10 ]; then
            find "$BACKUP_DIR" -name "spectra_pre_deploy_*.sql.gz" -type f | \
                sort | head -n -10 | xargs rm -f
            log "Cleaned up old backups (kept last 10)"
        fi
    fi
}

# ── Post-deploy: verify maintenance services ────────────────────

verify_maintenance_services() {
    log "Verifying maintenance services..."

    # Ensure BACKUP_ENABLED is set if not already configured
    if ! grep -q "BACKUP_ENABLED" "$PROJECT_DIR/.env" 2>/dev/null; then
        log "Setting BACKUP_ENABLED=true in .env (not previously configured)"
        echo "BACKUP_ENABLED=true" >> "$PROJECT_DIR/.env"
    fi

    # Verify scheduler service is running and healthy
    local scheduler_healthy=false
    for i in 1 2 3 4 5; do
        local scheduler_url="http://localhost:5020/health"
        if curl -sf --max-time 5 "$scheduler_url" 2>/dev/null | grep -q '"status"'; then
            scheduler_healthy=true
            break
        fi
        sleep 3
    done

    if [ "$scheduler_healthy" = true ]; then
        log "Scheduler service is healthy — automated maintenance active"
    else
        log "WARN: Scheduler health check failed — maintenance tasks may not be running"
    fi
}

# ── Main ─────────────────────────────────────────────────────────

main() {
    log "=== Deploy started: version=$VERSION ==="
    acquire_lock
    pre_deploy_check
    backup_database
    deploy
    verify_maintenance_services
    log "=== Deploy finished ==="
}

main
