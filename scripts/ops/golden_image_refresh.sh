#!/usr/bin/env bash
# scripts/ops/golden_image_refresh.sh — Rebuild golden images for worker pools
#
# Periodically rebuilds the worker/tools golden image to keep it current
# with latest security tool versions and OS patches.
#
# Usage:
#   ./scripts/ops/golden_image_refresh.sh                    # Build locally
#   ./scripts/ops/golden_image_refresh.sh --push REGISTRY    # Build and push to registry

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCKERFILE="${PROJECT_DIR}/docker/Dockerfile.tools"
IMAGE_NAME="spectra-tools"
KEEP_COUNT=3

PUSH=false
REGISTRY=""

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

validate_image() {
    local image="$1"
    local cid
    cid=$(docker run -d "$image" sleep 60) || { warn "Could not start validation container"; return 1; }
    local failed=0

    # Dynamically read tool commands from plugin configs
    for plugin_file in "${PROJECT_DIR}"/plugins/*.json; do
        [[ -f "$plugin_file" ]] || continue
        local plugin_name cmd
        plugin_name=$(basename "$plugin_file" .json)

        # Prefer the installation verification_command
        local verify_cmd
        verify_cmd=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get('installation', {}).get('verification_command', ''))
" "$plugin_file" 2>/dev/null)

        if [[ -n "$verify_cmd" ]]; then
            if ! docker exec "$cid" /bin/sh -c "$verify_cmd" > /dev/null 2>&1; then
                log "FAIL: ${plugin_name} — verification command failed: ${verify_cmd}"
                failed=1
            else
                log "  OK: ${plugin_name}"
            fi
            continue
        fi

        # Fallback: check the execution command binary exists
        cmd=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
c = d.get('execution', {}).get('command', '')
print(c.split()[0] if c else '')
" "$plugin_file" 2>/dev/null)

        [[ -z "$cmd" ]] && continue
        # Skip parameterised commands like "impacket-{sub_tool}"
        [[ "$cmd" == *"{"* ]] && continue

        if ! docker exec "$cid" which "$cmd" > /dev/null 2>&1; then
            log "FAIL: ${plugin_name} — ${cmd} not found"
            failed=1
        else
            log "  OK: ${plugin_name}"
        fi
    done

    docker stop "$cid" > /dev/null 2>&1 || true
    docker rm -f "$cid" > /dev/null 2>&1 || true
    return $failed
}

usage() {
    cat <<EOF
Golden Image Refresh — Spectra Worker Pools

Usage: $(basename "$0") [OPTIONS]

Options:
  --push REGISTRY   Push the built image to REGISTRY (e.g. ghcr.io/org)
  --help            Show this help message

Details:
  Builds ${IMAGE_NAME} from ${DOCKERFILE}
  Tags with: <version>-<YYYYMMDD> and 'latest'
  Keeps the ${KEEP_COUNT} most recent images, prunes older ones
EOF
    exit 0
}

# ── Argument parsing ─────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --push)
            [[ -z "${2:-}" ]] && die "--push requires a REGISTRY argument"
            PUSH=true
            REGISTRY="$2"
            shift 2
            ;;
        --help) usage ;;
        *)      die "Unknown option: $1" ;;
    esac
done

# ── Preflight ────────────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
docker info >/dev/null 2>&1       || die "Cannot connect to Docker daemon"
[[ -f "$DOCKERFILE" ]]            || die "Dockerfile not found: ${DOCKERFILE}"

# Read version from app/version.py
VERSION_FILE="${PROJECT_DIR}/app/version.py"
if [[ -f "$VERSION_FILE" ]]; then
    APP_VERSION=$(grep -oP '__version__\s*=\s*"\K[^"]+' "$VERSION_FILE" 2>/dev/null || echo "dev")
else
    APP_VERSION="dev"
fi

DATE_TAG=$(date -u '+%Y%m%d')
FULL_TAG="${APP_VERSION}-${DATE_TAG}"

log "=== Golden Image Refresh Started ==="
log "Image:   ${IMAGE_NAME}:${FULL_TAG}"
log "Version: ${APP_VERSION}"
log "Source:  ${DOCKERFILE}"

# ── Build ────────────────────────────────────────────────────────

log "--- Building golden image ---"

BUILD_START=$(date +%s)

docker build \
    --file "$DOCKERFILE" \
    --build-arg "BUILD_VERSION=${FULL_TAG}" \
    --label "spectra.managed=true" \
    --label "spectra.role=worker" \
    --label "spectra.golden=true" \
    --label "spectra.build-date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --tag "${IMAGE_NAME}:${FULL_TAG}" \
    "$PROJECT_DIR"

BUILD_END=$(date +%s)
BUILD_DURATION=$((BUILD_END - BUILD_START))

IMAGE_SIZE=$(docker image inspect "${IMAGE_NAME}:${FULL_TAG}" --format '{{.Size}}' 2>/dev/null || echo "0")
IMAGE_SIZE_MB=$(awk "BEGIN {printf \"%.1f\", ${IMAGE_SIZE} / 1024 / 1024}")

log "Build complete in ${BUILD_DURATION}s"
log "Image size: ${IMAGE_SIZE_MB} MB"

# ── Validate ─────────────────────────────────────────────────────

log "--- Validating golden image ---"

if validate_image "${IMAGE_NAME}:${FULL_TAG}"; then
    log "Validation passed — promoting to :latest"
    docker tag "${IMAGE_NAME}:${FULL_TAG}" "${IMAGE_NAME}:latest"
else
    log "FATAL: Validation FAILED — keeping previous :latest image"
    log "Removing failed image ${IMAGE_NAME}:${FULL_TAG}"
    docker rmi "${IMAGE_NAME}:${FULL_TAG}" 2>/dev/null || true
    exit 1
fi

# ── Push (optional) ─────────────────────────────────────────────

if [[ "$PUSH" == "true" ]]; then
    log "--- Pushing to registry: ${REGISTRY} ---"

    REMOTE_TAG="${REGISTRY}/${IMAGE_NAME}:${FULL_TAG}"
    REMOTE_LATEST="${REGISTRY}/${IMAGE_NAME}:latest"

    docker tag "${IMAGE_NAME}:${FULL_TAG}" "$REMOTE_TAG"
    docker tag "${IMAGE_NAME}:latest" "$REMOTE_LATEST"

    docker push "$REMOTE_TAG"
    docker push "$REMOTE_LATEST"

    log "Pushed: ${REMOTE_TAG}"
    log "Pushed: ${REMOTE_LATEST}"
fi

# ── Prune old golden images ─────────────────────────────────────

log "--- Pruning old golden images (keeping newest ${KEEP_COUNT}) ---"

# List all spectra-tools images sorted by creation (newest first), excluding 'latest' tag
golden_images=$(docker images "${IMAGE_NAME}" --format "{{.CreatedAt}}\t{{.ID}}\t{{.Repository}}:{{.Tag}}" \
    2>/dev/null | grep -v ":latest$" | sort -r || true)

if [[ -n "$golden_images" ]]; then
    total=$(echo "$golden_images" | wc -l)

    if [[ "$total" -gt "$KEEP_COUNT" ]]; then
        to_remove=$(echo "$golden_images" | tail -n +"$((KEEP_COUNT + 1))")
        remove_count=$(echo "$to_remove" | wc -l)

        log "Removing ${remove_count} old golden image(s)"

        echo "$to_remove" | while IFS=$'\t' read -r _created img_id img_tag; do
            if ! docker ps -q --filter "ancestor=${img_id}" 2>/dev/null | grep -q .; then
                if docker rmi "$img_tag" 2>/dev/null; then
                    log "Removed: ${img_tag}"
                else
                    warn "Could not remove ${img_tag} (may be in use)"
                fi
            else
                warn "Skipping ${img_tag} — still in use by running container"
            fi
        done
    else
        log "Only ${total} image(s) found, nothing to prune"
    fi
else
    log "No previous golden images found"
fi

# ── Summary ──────────────────────────────────────────────────────

log "=== Golden Image Refresh Complete ==="
log "Tag:        ${IMAGE_NAME}:${FULL_TAG}"
log "Size:       ${IMAGE_SIZE_MB} MB"
log "Build time: ${BUILD_DURATION}s"
if [[ "$PUSH" == "true" ]]; then
    log "Registry:   ${REGISTRY}/${IMAGE_NAME}:${FULL_TAG}"
fi
