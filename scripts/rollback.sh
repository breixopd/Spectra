#!/bin/bash
# Spectra Rollback Script
# Usage: ./scripts/rollback.sh [version]
#
# Rolls back to a previous version, restores DB from most recent backup,
# and sends a rollback notification.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HEALTH_CHECK="$SCRIPT_DIR/health_check.sh"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/deploy.log"
BACKUP_DIR="$PROJECT_DIR/data/backups"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_DIR/deploy/docker/compose.yaml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${APP_PORT:-5000}/api/health/ready}"
DEPLOY_WEBHOOK_URL="${DEPLOY_WEBHOOK_URL:-}"
TARGET_VERSION="${1:-}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [version]

Arguments:
  version   Immutable version tag to rollback to (required; latest/dev are rejected).

Environment variables:
  COMPOSE_FILE        Docker compose file (default: deploy/docker/compose.yaml)
  DEPLOY_WEBHOOK_URL  Webhook URL for rollback notifications (optional)
  HEALTH_URL          Health check URL (default: http://localhost:80/api/v1/health?scope=public)

Examples:
  $(basename "$0") 2026.03.11         # Rollback to specific version
  $(basename "$0") 2026.07.18.1 --yes # Restore a known release
EOF
    exit 0
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
fi

# ── Confirmation guard ────────────────────────────────────────────

FORCED=false
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--yes" ] || [ "$arg" = "-y" ] || [ "$arg" = "--force" ]; then
        FORCED=true
    else
        ARGS+=("$arg")
    fi
done

# Re-assign TARGET_VERSION from filtered args
TARGET_VERSION="${ARGS[0]:-}"

if [ "$FORCED" != "true" ]; then
    echo "WARNING: This will overwrite the database. Use --yes to confirm." >&2
    exit 1
fi

mkdir -p "$LOG_DIR"

log() {
    local msg
    msg="[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] [ROLLBACK] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

notify() {
    local status="$1" message="$2"
    if [ -n "$DEPLOY_WEBHOOK_URL" ]; then
        local payload
        payload=$(python3 -c "import json,sys; print(json.dumps({'text': '[Spectra Rollback] ' + sys.argv[1] + ': ' + sys.argv[2] + ' (target: ' + sys.argv[3] + ')'}))" "$status" "$message" "${TARGET_VERSION:-current}")
        curl -sf --max-time 10 -X POST -H 'Content-Type: application/json' \
            -d "$payload" "$DEPLOY_WEBHOOK_URL" > /dev/null 2>&1 || true
    fi
}

# ── Signal handling ──────────────────────────────────────────────

trap 'log "Rollback interrupted"; exit 130' INT
trap 'log "Rollback terminated"; exit 143' TERM

# ── Database restore ─────────────────────────────────────────────

restore_database() {
    local backup_file
    backup_file=$(find "$BACKUP_DIR" -name "spectra_pre_deploy_*.sql.gz" -type f 2>/dev/null | sort | tail -n 1)

    if [ -z "$backup_file" ]; then
        log "WARN: No database backups found in $BACKUP_DIR — skipping DB restore"
        return 0
    fi

    log "Restoring database from: $backup_file"

    # Wait for DB to be ready via pg_isready before restoring
    local retries=10
    while [ $retries -gt 0 ]; do
        if pg_isready -h db -U spectra -d spectra > /dev/null 2>&1 || \
           docker exec spectra-db pg_isready -U spectra -d spectra > /dev/null 2>&1; then
            break
        fi
        retries=$((retries - 1))
        sleep 2
    done

    if [ $retries -eq 0 ]; then
        log "ERROR: Database container not ready — cannot restore"
        return 1
    fi

    if gunzip -c "$backup_file" | docker exec -i spectra-db psql --single-transaction --set ON_ERROR_STOP=1 -U spectra -d spectra; then
        log "Database restored successfully from $backup_file"
    else
        log "ERROR: Database restore failed"
        return 1
    fi
}

# ── Main ─────────────────────────────────────────────────────────

main() {
    log "=== Rollback started ==="
    notify "STARTING" "Rollback initiated"

    # Check compose file
    if [ ! -f "$COMPOSE_FILE" ]; then
        log "ERROR: Compose file not found: $COMPOSE_FILE"
        exit 1
    fi

    local version_arg="${TARGET_VERSION:-latest}"
    if [[ -z "$version_arg" || "$version_arg" == "latest" || "$version_arg" == "dev" ]]; then
        log "ERROR: Cannot rollback without an immutable pinned version"
        log "Usage: $(basename "$0") <version>  (e.g. 2026.07.18.1)"
        notify "FAILED" "Cannot rollback — no pinned version"
        exit 1
    fi

    # Stop current containers
    log "Stopping current containers..."
    docker compose -f "$COMPOSE_FILE" down --timeout 30 2>/dev/null || true

    # Restart with target version (or current)
    log "Starting containers with version: $version_arg"

    if [ -n "$TARGET_VERSION" ]; then
        VERSION="$TARGET_VERSION" docker compose -f "$COMPOSE_FILE" pull
    fi

    VERSION="$version_arg" docker compose -f "$COMPOSE_FILE" --profile app up -d

    # Wait for DB before restoring
    log "Waiting for services to start..."
    sleep 10

    # Restore database
    restore_database

    # Health check
    log "Running post-rollback health check..."
    if bash "$HEALTH_CHECK" "$HEALTH_URL" 5 3; then
        log "Rollback successful: version $version_arg is healthy"
        notify "SUCCESS" "Rollback completed — version $version_arg is live"
    else
        log "ERROR: Post-rollback health check failed — manual intervention required"
        notify "CRITICAL" "Rollback health check failed — manual intervention required"
        exit 1
    fi

    log "=== Rollback finished ==="
}

main
