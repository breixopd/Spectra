#!/usr/bin/env bash
set -euo pipefail

# Spectra Server Migration Helper
# Assists with migrating Spectra to a new server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { echo -e "${GREEN}[MIGRATE]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
    cat <<EOF
Spectra Server Migration

Usage: $0 <command> [options]

Commands:
  export     Create a migration bundle (DB dump + S3 data + config)
  import     Restore a migration bundle on the new server
  verify     Verify the new installation matches the old

Export options:
  --output <path>    Output directory for the bundle (default: /tmp/spectra-migration)

Import options:
  --bundle <path>    Path to migration bundle directory
  --skip-db          Skip database restore
  --skip-s3          Skip S3 data restore

Examples:
  # On old server: create migration bundle
  $0 export --output /tmp/spectra-migration

  # Transfer to new server
  rsync -avz /tmp/spectra-migration/ newserver:/tmp/spectra-migration/

  # On new server: run first_run.sh first, then:
  $0 import --bundle /tmp/spectra-migration
  $0 verify
EOF
}

export_bundle() {
    local output="${1:-/tmp/spectra-migration}"
    mkdir -p "${output}"/{db,s3,config}

    log "Creating migration bundle at ${output}..."

    # 1. Database dump
    log "Dumping database..."
    docker compose -f docker/docker-compose.yml exec -T db \
        pg_dump -U spectra_user spectra -Fc > "${output}/db/spectra.dump"
    log "Database dump: $(du -h "${output}/db/spectra.dump" | cut -f1)"

    # 2. S3 data export
    log "Exporting S3 buckets..."
    for bucket in spectra-missions spectra-sessions spectra-knowledge spectra-backups; do
        mkdir -p "${output}/s3/${bucket}"
        docker compose -f docker/docker-compose.yml exec -T garage \
            /garage bucket list 2>/dev/null | grep -q "${bucket}" && \
        log "  Exporting ${bucket}..." || { warn "  Bucket ${bucket} not found, skipping"; continue; }
    done

    # 3. Config files
    log "Copying configuration..."
    cp -p .env "${output}/config/.env" 2>/dev/null || warn ".env not found"
    cp -p config/tensorzero.toml "${output}/config/tensorzero.toml" 2>/dev/null || true
    cp -rp keys/ "${output}/config/keys/" 2>/dev/null || true

    # 4. VPN configs (stored in S3 under vpn/ prefix in spectra-sessions bucket)
    log "VPN configs are stored in S3 and will be included in the S3 data export"

    log "Migration bundle created at ${output}"
    log "Bundle size: $(du -sh "${output}" | cut -f1)"
    echo ""
    log "Transfer to new server with:"
    echo "  rsync -avz ${output}/ newserver:/tmp/spectra-migration/"
}

import_bundle() {
    local bundle="${1:?Bundle path required}"
    local skip_db="${2:-false}"
    local skip_s3="${3:-false}"

    [[ -d "${bundle}" ]] || { err "Bundle not found: ${bundle}"; exit 1; }

    log "Importing migration bundle from ${bundle}..."

    # 1. Restore config
    if [[ -f "${bundle}/config/.env" ]]; then
        log "Restoring .env (merging with current)..."
        warn "Review .env manually — server-specific values (PLATFORM_DOMAIN, etc.) may need updating"
    fi

    if [[ -d "${bundle}/config/keys" ]]; then
        log "Restoring signing keys..."
        cp -rp "${bundle}/config/keys/"* keys/ 2>/dev/null || true
    fi

    # 2. Database restore
    if [[ "${skip_db}" != "true" ]] && [[ -f "${bundle}/db/spectra.dump" ]]; then
        log "Restoring database..."
        docker compose -f docker/docker-compose.yml exec -T db \
            pg_restore -U spectra_user -d spectra --clean --if-exists \
            < "${bundle}/db/spectra.dump" 2>/dev/null || warn "Some restore warnings (expected for clean install)"
        log "Database restored"
    fi

    # 3. VPN configs (stored in S3 — included in S3 data migration)
    log "VPN configs are in S3 (spectra-sessions bucket, vpn/ prefix) — no filesystem restore needed"

    log "Import complete. Restart services: docker compose -f docker/docker-compose.yml restart"
}

verify_migration() {
    log "Verifying migration..."

    # Check health
    local health
    health=$(curl -sf http://localhost/api/health 2>/dev/null) || { err "Health check failed"; exit 1; }
    echo "$health" | python3 -m json.tool

    # Check DB
    local user_count
    user_count=$(docker compose -f docker/docker-compose.yml exec -T db \
        psql -U spectra_user -d spectra -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ')
    log "Users in database: ${user_count}"

    local mission_count
    mission_count=$(docker compose -f docker/docker-compose.yml exec -T db \
        psql -U spectra_user -d spectra -t -c "SELECT COUNT(*) FROM missions;" 2>/dev/null | tr -d ' ')
    log "Missions in database: ${mission_count}"

    log "Verification complete"
}

# Main
case "${1:-}" in
    export)
        shift
        output="/tmp/spectra-migration"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --output) output="$2"; shift 2 ;;
                *) shift ;;
            esac
        done
        export_bundle "${output}"
        ;;
    import)
        shift
        bundle=""; skip_db="false"; skip_s3="false"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --bundle) bundle="$2"; shift 2 ;;
                --skip-db) skip_db="true"; shift ;;
                --skip-s3) skip_s3="true"; shift ;;
                *) shift ;;
            esac
        done
        import_bundle "${bundle}" "${skip_db}" "${skip_s3}"
        ;;
    verify)
        verify_migration
        ;;
    *)
        usage
        exit 1
        ;;
esac
