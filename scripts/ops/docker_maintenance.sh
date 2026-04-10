#!/usr/bin/env bash
# scripts/ops/docker_maintenance.sh — Docker cleanup for ephemeral worker hosts
#
# Runs as a periodic maintenance job to prevent disk exhaustion from
# accumulated containers, images, volumes, and build cache.
#
# Usage:
#   ./scripts/ops/docker_maintenance.sh              # Standard cleanup
#   ./scripts/ops/docker_maintenance.sh --aggressive  # Include build cache + old images
#   ./scripts/ops/docker_maintenance.sh --dry-run     # Show what would be cleaned
#
# Designed to run via cron:
#   0 3 * * * /path/to/scripts/ops/docker_maintenance.sh --aggressive >> /var/log/spectra-maintenance.log 2>&1
# ⚠ DEPRECATED (auto-cleanup) — The scheduler's docker_cleanup task
# prunes unused images and containers automatically. Use this for
# aggressive manual cleanup on worker hosts.

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────

LABEL_MANAGED="spectra.managed=true"
BUILD_CACHE_MAX_AGE="168h"          # 7 days
AGGRESSIVE_IMAGE_AGE="48h"         # --aggressive: remove images older than this
GOLDEN_KEEP_COUNT=3                # golden images to retain

DRY_RUN=false
AGGRESSIVE=false

# ── Helpers ──────────────────────────────────────────────────────

log() {
    printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

warn() {
    log "WARN: $*" >&2
}

die() {
    log "FATAL: $*" >&2
    exit 1
}

usage() {
    cat <<EOF
Docker Maintenance — Spectra Worker Host Cleanup

Usage: $(basename "$0") [OPTIONS]

Options:
  --dry-run      Show what would be cleaned without removing anything
  --aggressive   Also prune build cache (>${BUILD_CACHE_MAX_AGE} old) and
                 unused images older than ${AGGRESSIVE_IMAGE_AGE}
  --help         Show this help message

Safety:
  - Never removes running containers
  - Never removes named volumes unless they are orphaned
  - Respects spectra.managed label for container identification
EOF
    exit 0
}

# ── Argument parsing ─────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true;    shift ;;
        --aggressive) AGGRESSIVE=true; shift ;;
        --help)       usage ;;
        *)            die "Unknown option: $1" ;;
    esac
done

# ── Preflight ────────────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
docker info >/dev/null 2>&1       || die "Cannot connect to Docker daemon"

if [[ "$DRY_RUN" == "true" ]]; then
    log "=== DRY-RUN MODE — no changes will be made ==="
fi

# ── Disk usage snapshot (before) ─────────────────────────────────

log "=== Docker Maintenance Started ==="

log "--- Disk usage BEFORE cleanup ---"
docker system df 2>/dev/null || true

# ── 1. Prune stopped containers ─────────────────────────────────

log "--- Pruning stopped containers ---"

stopped_containers=$(docker ps -a --filter "status=exited" --filter "status=dead" --filter "status=created" -q 2>/dev/null || true)
if [[ -n "$stopped_containers" ]]; then
    count=$(echo "$stopped_containers" | wc -l)
    log "Found ${count} stopped container(s)"

    if [[ "$DRY_RUN" == "true" ]]; then
        log "[dry-run] Would remove:"
        docker ps -a --filter "status=exited" --filter "status=dead" --filter "status=created" \
            --format "  {{.ID}}  {{.Names}}  ({{.Status}}, image={{.Image}})" 2>/dev/null || true
    else
        docker container prune -f 2>/dev/null
        log "Removed ${count} stopped container(s)"
    fi
else
    log "No stopped containers found"
fi

# ── 2. Prune dangling images ────────────────────────────────────

log "--- Pruning dangling images ---"

dangling=$(docker images -f "dangling=true" -q 2>/dev/null || true)
if [[ -n "$dangling" ]]; then
    count=$(echo "$dangling" | wc -l)
    log "Found ${count} dangling image(s)"

    if [[ "$DRY_RUN" == "true" ]]; then
        log "[dry-run] Would remove:"
        docker images -f "dangling=true" --format "  {{.ID}}  {{.Repository}}:{{.Tag}}  ({{.Size}}, created {{.CreatedSince}})" 2>/dev/null || true
    else
        docker image prune -f 2>/dev/null
        log "Removed ${count} dangling image(s)"
    fi
else
    log "No dangling images found"
fi

# ── 3. Aggressive: remove unused images older than threshold ─────

if [[ "$AGGRESSIVE" == "true" ]]; then
    log "--- Aggressive: pruning unused images older than ${AGGRESSIVE_IMAGE_AGE} ---"

    if [[ "$DRY_RUN" == "true" ]]; then
        log "[dry-run] Would prune images not used for ${AGGRESSIVE_IMAGE_AGE}:"
        # Show candidates (images not referenced by any container)
        docker images --format "  {{.ID}}  {{.Repository}}:{{.Tag}}  ({{.Size}}, created {{.CreatedSince}})" \
            --filter "dangling=false" 2>/dev/null | head -20 || true
    else
        docker image prune -a -f --filter "until=${AGGRESSIVE_IMAGE_AGE}" 2>/dev/null
        log "Pruned unused images older than ${AGGRESSIVE_IMAGE_AGE}"
    fi
fi

# ── 4. Prune unused volumes ─────────────────────────────────────

log "--- Pruning unused anonymous volumes ---"

# Only prune anonymous (unnamed) volumes — docker volume prune -f
# removes volumes not referenced by any container. Named compose volumes
# are safe because their containers are typically running.
unused_volumes=$(docker volume ls -f "dangling=true" -q 2>/dev/null || true)
if [[ -n "$unused_volumes" ]]; then
    count=$(echo "$unused_volumes" | wc -l)
    log "Found ${count} unused volume(s)"

    if [[ "$DRY_RUN" == "true" ]]; then
        log "[dry-run] Would remove:"
        while IFS= read -r vol; do printf '  %s\n' "$vol"; done <<< "$unused_volumes"
    else
        docker volume prune -f 2>/dev/null
        log "Removed ${count} unused volume(s)"
    fi
else
    log "No unused volumes found"
fi

# ── 5. Prune unused networks ────────────────────────────────────

log "--- Pruning unused networks ---"

if [[ "$DRY_RUN" == "true" ]]; then
    stale_nets=$(docker network ls --filter "type=custom" -q 2>/dev/null || true)
    if [[ -n "$stale_nets" ]]; then
        log "[dry-run] Would prune unused custom networks:"
        docker network ls --filter "type=custom" --format "  {{.ID}}  {{.Name}}  ({{.Driver}})" 2>/dev/null || true
    else
        log "No unused networks found"
    fi
else
    docker network prune -f 2>/dev/null
    log "Pruned unused networks"
fi

# ── 6. Clean build cache ────────────────────────────────────────

if [[ "$AGGRESSIVE" == "true" ]]; then
    log "--- Aggressive: pruning build cache older than ${BUILD_CACHE_MAX_AGE} ---"

    if [[ "$DRY_RUN" == "true" ]]; then
        log "[dry-run] Would prune build cache older than ${BUILD_CACHE_MAX_AGE}"
        docker builder du 2>/dev/null | tail -3 || true
    else
        docker builder prune -f --filter "until=${BUILD_CACHE_MAX_AGE}" 2>/dev/null
        log "Pruned build cache older than ${BUILD_CACHE_MAX_AGE}"
    fi
fi

# ── 7. Golden image cleanup ─────────────────────────────────────

log "--- Golden image housekeeping ---"

# List spectra-tools golden images sorted by creation date (newest first)
golden_images=$(docker images "spectra-tools" --format "{{.CreatedAt}}\t{{.ID}}\t{{.Repository}}:{{.Tag}}" 2>/dev/null \
    | sort -r || true)

if [[ -n "$golden_images" ]]; then
    total=$(echo "$golden_images" | wc -l)
    log "Found ${total} golden image(s) (keeping newest ${GOLDEN_KEEP_COUNT})"

    if [[ "$total" -gt "$GOLDEN_KEEP_COUNT" ]]; then
        to_remove=$(echo "$golden_images" | tail -n +"$((GOLDEN_KEEP_COUNT + 1))" | awk -F'\t' '{print $2}')

        if [[ "$DRY_RUN" == "true" ]]; then
            log "[dry-run] Would remove old golden images:"
            echo "$golden_images" | tail -n +"$((GOLDEN_KEEP_COUNT + 1))" | awk -F'\t' '{print "  " $3 "  (" $1 ")"}'
        else
            echo "$to_remove" | while read -r img_id; do
                # Only remove if not in use by any container
                if ! docker ps -q --filter "ancestor=${img_id}" 2>/dev/null | grep -q .; then
                    if docker rmi "$img_id" 2>/dev/null; then
                        log "Removed old golden image: ${img_id}"
                    else
                        warn "Could not remove golden image ${img_id} (may be in use)"
                    fi
                else
                    warn "Skipping golden image ${img_id} — still in use by running container"
                fi
            done
        fi
    else
        log "All golden images within retention limit"
    fi
else
    log "No golden images found"
fi

# ── 8. Report: stale Spectra sandbox containers ──────────────────

log "--- Spectra sandbox container check ---"

stale_sandboxes=$(docker ps -a --filter "label=${LABEL_MANAGED}" \
    --filter "status=exited" --filter "status=dead" \
    --format "{{.ID}}  {{.Names}}  ({{.Status}})" 2>/dev/null || true)

if [[ -n "$stale_sandboxes" ]]; then
    log "Stale Spectra-managed containers (already removed above if stopped):"
    while IFS= read -r line; do printf '  %s\n' "$line"; done <<< "$stale_sandboxes"
else
    log "No stale Spectra-managed containers"
fi

# ── Disk usage snapshot (after) ──────────────────────────────────

log "--- Disk usage AFTER cleanup ---"
docker system df 2>/dev/null || true

log "=== Docker Maintenance Complete ==="
