#!/usr/bin/env bash
# scripts/ops/golden_image_refresh.sh — Build the golden worker image with all tools pre-installed
#
# Reads every plugin from plugins/*.json, generates a Dockerfile that installs
# all of them (via apt, pip, go, or custom scripts), builds the image, validates
# every tool is functional, optionally pushes to a registry, and prunes old images.
#
# This is the PRIMARY path for tool delivery — tools should NEVER be installed
# on-demand in production. On-demand install in tool_jobs.py is a FALLBACK for
# plugins added AFTER the golden image was built (e.g. user-uploaded plugins).
#
# Usage:
#   ./scripts/ops/golden_image_refresh.sh                         # Build locally
#   ./scripts/ops/golden_image_refresh.sh --push ghcr.io/org      # Build + push
#   ./scripts/ops/golden_image_refresh.sh --tag custom-tag        # Custom tag
#   ./scripts/ops/golden_image_refresh.sh --help                  # Show help

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLUGINS_DIR="${PROJECT_DIR}/plugins"
IMAGE_NAME="spectra-tools"
DEFAULT_BASE_IMAGE="kalilinux/kali-rolling:latest"
KEEP_COUNT=3

PUSH=false
REGISTRY=""
CUSTOM_TAG=""

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
Golden Image Refresh — Spectra Worker Pools

Builds a golden Docker image with all security tools from plugins/*.json
pre-installed. Tools are baked into the image at build time — not installed
on-demand at runtime.

Usage: $(basename "$0") [OPTIONS]

Options:
  --push REGISTRY   Push the built image to REGISTRY (e.g. ghcr.io/org)
  --tag TAG         Use a custom tag instead of <version>-<YYYYMMDD>
  --help            Show this help message

Details:
  Image name: ${IMAGE_NAME}
  Base:       ${DEFAULT_BASE_IMAGE}
  Tags:       <version>-<YYYYMMDD> and 'latest'
  Keeps:      ${KEEP_COUNT} most recent images
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
        --tag)
            [[ -z "${2:-}" ]] && die "--tag requires an argument"
            CUSTOM_TAG="$2"
            shift 2
            ;;
        --help) usage ;;
        *)      die "Unknown option: $1" ;;
    esac
done

# ── Preflight ────────────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
docker info >/dev/null 2>&1       || die "Cannot connect to Docker daemon"
[[ -d "$PLUGINS_DIR" ]]           || die "Plugins directory not found: ${PLUGINS_DIR}"

# Count plugins
PLUGIN_COUNT=$(find "$PLUGINS_DIR" -maxdepth 1 -name '*.json' | wc -l)
[[ "$PLUGIN_COUNT" -gt 0 ]] || die "No plugin JSON files found in ${PLUGINS_DIR}"

# Read version
VERSION_FILE="${PROJECT_DIR}/packages/platform/src/spectra_platform/_meta/version.py"
if [[ -f "$VERSION_FILE" ]]; then
    APP_VERSION=$(grep -oP 'DEFAULT_VERSION\s*=\s*"\K[^"]+' "$VERSION_FILE" 2>/dev/null || echo "dev")
else
    APP_VERSION="dev"
fi

DATE_TAG=$(date -u '+%Y%m%d')
if [[ -n "$CUSTOM_TAG" ]]; then
    FULL_TAG="$CUSTOM_TAG"
else
    FULL_TAG="${APP_VERSION}-${DATE_TAG}"
fi

log "=== Golden Image Refresh Started ==="
log "Image:       ${IMAGE_NAME}:${FULL_TAG}"
log "Base:        ${DEFAULT_BASE_IMAGE}"
log "Version:     ${APP_VERSION}"
log "Plugins:     ${PLUGIN_COUNT}"
log "Push:        ${PUSH}${REGISTRY:+ → ${REGISTRY}}"

# ── Step 1: Generate Dockerfile from plugin definitions ──────────

log "--- Generating Dockerfile from ${PLUGIN_COUNT} plugins ---"

# Use Python to read all plugin JSONs and produce the Dockerfile content.
# This mirrors GoldenImageBuilder.generate_dockerfile() in the Python codebase.
DOCKERFILE_CONTENT=$(python3 -c "
import hashlib, json, shlex, sys
from pathlib import Path

plugins_dir = Path('${PLUGINS_DIR}')
SANDBOX_BASE_IMAGE = '${DEFAULT_BASE_IMAGE}'

plugins = []
for json_file in sorted(plugins_dir.glob('*.json')):
    try:
        data = json.loads(json_file.read_text())
        installation = data.get('installation', {})
        if not installation:
            continue
        plugins.append({
            'id': data.get('id', json_file.stem),
            'name': data.get('name', json_file.stem),
            'version': data.get('version', ''),
            'install_method': installation.get('method', ''),
            'install_commands': installation.get('commands', []),
            'verification_command': installation.get('verification_command', ''),
        })
    except (json.JSONDecodeError, KeyError) as exc:
        print(f'WARN: Skipping malformed plugin {json_file.name}: {exc}', file=sys.stderr)

if not plugins:
    print('ERROR: No valid plugins found', file=sys.stderr)
    sys.exit(1)

# Build manifest digest
manifest = [
    {'id': p['id'], 'name': p['name'], 'version': p['version'],
     'install_method': p['install_method'],
     'verification_command': p['verification_command'],
     'install_commands_sha256': hashlib.sha256(
         json.dumps(p['install_commands'], sort_keys=True).encode()
     ).hexdigest()}
    for p in sorted(plugins, key=lambda x: str(x.get('id', '')))
]
manifest_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
tool_ids = ','.join(m['id'] for m in manifest)

# Group install commands by method
apt_packages = []
pip_packages = []
custom_commands = []
go_packages = []

for p in plugins:
    method = p['install_method']
    commands = p['install_commands']
    if method == 'apt':
        for cmd in commands:
            try:
                parts = shlex.split(cmd)
            except ValueError:
                continue
            for i, part in enumerate(parts[:-1]):
                if part not in {'apt', 'apt-get'} or parts[i+1] != 'install':
                    continue
                for token in parts[i+2:]:
                    if token in {'&&', '||', ';', '|'} or token.startswith('('):
                        break
                    if token.startswith('-'):
                        continue
                    if token not in apt_packages:
                        apt_packages.append(token)
    elif method == 'pip':
        for cmd in commands:
            try:
                parts = shlex.split(cmd)
            except ValueError:
                continue
            for i, part in enumerate(parts[:-1]):
                if part not in {'pip', 'pip3'} or parts[i+1] != 'install':
                    continue
                for token in parts[i+2:]:
                    if token in {'&&', '||', ';', '|'} or token.startswith('('):
                        break
                    if token.startswith('-'):
                        continue
                    if token not in pip_packages:
                        pip_packages.append(token)
    elif method == 'go':
        for cmd in commands:
            if 'go install' in cmd:
                go_packages.append(cmd)
    elif method == 'script':
        custom_commands.extend(commands)

lines = []
lines.append(f'FROM {SANDBOX_BASE_IMAGE}')
lines.append('')
lines.append('LABEL org.opencontainers.image.title=\"Spectra Tools (Golden)\"')
lines.append('LABEL org.opencontainers.image.description=\"Auto-built security tools image\"')
lines.append(f'LABEL io.spectra.golden-image.manifest-sha256=\"{manifest_sha}\"')
lines.append(f'LABEL io.spectra.golden-image.plugins=\"{tool_ids}\"')
lines.append('')
lines.append('WORKDIR /app')
lines.append('')
lines.append('# System packages + tool packages')
lines.append('RUN apt-get update && \\\\')
lines.append('    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \\\\')
lines.append('    python3 python3-pip python3-venv python3-dev \\\\')
lines.append('    gcc libpq-dev libffi-dev pkg-config libpcap-dev \\\\')
lines.append('    curl wget git jq unzip \\\\')
lines.append('    iputils-ping iproute2 netcat-openbsd iptables \\\\')
lines.append('    wireguard-tools openvpn \\\\')
lines.append('    golang \\\\')
if apt_packages:
    deduped_apt = sorted(set(apt_packages))
    lines.append(f'    {\" \".join(deduped_apt)} \\\\')
lines.append('    && apt-get clean \\\\')
lines.append('    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*')
lines.append('')
lines.append('# Go setup')
lines.append('ENV GOPATH=/root/go')
lines.append('ENV PATH=\$PATH:/root/go/bin:/usr/local/go/bin')
lines.append('')
lines.append('# Python virtualenv')
lines.append('RUN python3 -m venv /opt/venv')
lines.append('ENV PATH=\"/opt/venv/bin:/opt/spectra_tools:\$PATH\"')
lines.append('')
lines.append('# Python dependencies')
lines.append('COPY requirements/worker.txt .')
lines.append('RUN pip install --no-cache-dir --upgrade pip && \\\\')
lines.append('    pip install --no-cache-dir -r worker.txt')
lines.append('')
if pip_packages:
    deduped_pip = sorted(set(pip_packages))
    lines.append(f'RUN pip install --no-cache-dir {\" \".join(deduped_pip)}')
    lines.append('')
if go_packages:
    lines.append('# Go tools')
    for cmd in go_packages:
        lines.append(f'RUN {cmd}')
    lines.append('')
if custom_commands:
    lines.append('# Custom tool installations')
    for cmd in custom_commands:
        lines.append(f'RUN {cmd}')
    lines.append('')
lines.append('# Worker code')
lines.append('COPY services/worker/src/spectra_worker/ ./spectra_worker/')
lines.append('COPY services/ai/src/spectra_ai/ ./spectra_ai/')
lines.append('COPY packages/tools-core/src/spectra_tools_core/ ./spectra_tools_core/')
lines.append('COPY packages/common/src/spectra_common/ ./spectra_common/')
lines.append('COPY packages/domain/src/spectra_domain/ ./spectra_domain/')
lines.append('COPY packages/platform/src/spectra_platform/ ./spectra_platform/')
lines.append('COPY plugins/ ./plugins/')
lines.append('')
lines.append('# Entrypoint')
lines.append('CMD [\"python\", \"-m\", \"spectra_worker\"]')

print('\\n'.join(lines))
") || die "Failed to generate Dockerfile content"

# Write Dockerfile to a temp location for the build context
TEMP_DOCKERFILE=$(mktemp "${PROJECT_DIR}/golden_image.Dockerfile.XXXXXXXX")
echo "$DOCKERFILE_CONTENT" > "$TEMP_DOCKERFILE"

# Clean up temp Dockerfile on exit
cleanup() {
    rm -f "$TEMP_DOCKERFILE"
}
trap cleanup EXIT

DOCKERFILE_LINES=$(echo "$DOCKERFILE_CONTENT" | wc -l)
log "Generated Dockerfile: ${DOCKERFILE_LINES} lines"
log "Plugins baked in: ${tool_ids}"

# ── Step 2: Build golden image ───────────────────────────────────

log "--- Building golden image ---"

BUILD_START=$(date +%s)

docker build \
    --file "$TEMP_DOCKERFILE" \
    --build-arg "BUILD_VERSION=${FULL_TAG}" \
    --label "spectra.managed=true" \
    --label "spectra.role=worker" \
    --label "spectra.golden=true" \
    --label "spectra.build-date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --label "spectra.plugins=${tool_ids}" \
    --tag "${IMAGE_NAME}:${FULL_TAG}" \
    "$PROJECT_DIR" 2>&1 | while IFS= read -r line; do
        # Suppress noisy build output unless it's an error
        if [[ "$line" == *"error"* ]] || [[ "$line" == *"ERROR"* ]] || [[ "$line" == *"failed"* ]]; then
            echo "$line" >&2
        fi
    done

BUILD_END=$(date +%s)
BUILD_DURATION=$((BUILD_END - BUILD_START))

# Verify build succeeded
if ! docker image inspect "${IMAGE_NAME}:${FULL_TAG}" >/dev/null 2>&1; then
    die "Build failed — image ${IMAGE_NAME}:${FULL_TAG} not found after build"
fi

IMAGE_SIZE=$(docker image inspect "${IMAGE_NAME}:${FULL_TAG}" --format '{{.Size}}' 2>/dev/null || echo "0")
IMAGE_SIZE_MB=$(awk "BEGIN {printf \"%.1f\", ${IMAGE_SIZE} / 1024 / 1024}")

log "Build complete in ${BUILD_DURATION}s"
log "Image size: ${IMAGE_SIZE_MB} MB"

# ── Step 3: Validate golden image ────────────────────────────────

log "--- Validating golden image ---"

validate_image() {
    local image="$1"
    local cid
    cid=$(docker run -d "$image" sleep 60) || { warn "Could not start validation container"; return 1; }
    local failed=0
    local passed=0
    local skipped=0

    for plugin_file in "$PLUGINS_DIR"/*.json; do
        [[ -f "$plugin_file" ]] || continue
        local plugin_name
        plugin_name=$(basename "$plugin_file" .json)

        # Prefer the installation verification_command
        local verify_cmd
        verify_cmd=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get('installation', {}).get('verification_command', ''))
" "$plugin_file" 2>/dev/null)

        if [[ -n "$verify_cmd" ]]; then
            # Sanity: reject suspicious verification commands
            if echo "$verify_cmd" | grep -qE '[;&|`$(){}\[\]<>]'; then
                warn "Skipping verification for ${plugin_name}: suspicious command: ${verify_cmd}"
                skipped=$((skipped + 1))
                continue
            fi
            if docker exec "$cid" /bin/sh -c "$verify_cmd" > /dev/null 2>&1; then
                log "  OK: ${plugin_name} (verification)"
                passed=$((passed + 1))
            else
                log "FAIL: ${plugin_name} — verification command failed: ${verify_cmd}"
                failed=1
            fi
            continue
        fi

        # Fallback: check the execution command binary exists
        local cmd
        cmd=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
c = d.get('execution', {}).get('command', '')
print(c.split()[0] if c else '')
" "$plugin_file" 2>/dev/null)

        [[ -z "$cmd" ]] && { skipped=$((skipped + 1)); continue; }
        # Skip parameterised commands like "impacket-{sub_tool}"
        [[ "$cmd" == *"{"* ]] && { skipped=$((skipped + 1)); continue; }

        # Check with 'which' first, then 'command -v' as fallback
        if docker exec "$cid" sh -c "which \"$cmd\" 2>/dev/null || command -v \"$cmd\" 2>/dev/null" > /dev/null 2>&1; then
            log "  OK: ${plugin_name} (${cmd})"
            passed=$((passed + 1))
        else
            log "FAIL: ${plugin_name} — ${cmd} not found in PATH"
            failed=1
        fi
    done

    docker stop "$cid" > /dev/null 2>&1 || true
    docker rm -f "$cid" > /dev/null 2>&1 || true

    log "Validation: ${passed} passed, ${skipped} skipped, $([ "$failed" -eq 1 ] && echo 'SOME FAILED' || echo 'ALL PASSED')"
    return $failed
}

if validate_image "${IMAGE_NAME}:${FULL_TAG}"; then
    log "Validation PASSED — promoting to :latest"
    docker tag "${IMAGE_NAME}:${FULL_TAG}" "${IMAGE_NAME}:latest"
else
    log "FATAL: Validation FAILED — keeping previous :latest image"
    log "Removing failed image ${IMAGE_NAME}:${FULL_TAG}"
    docker rmi "${IMAGE_NAME}:${FULL_TAG}" 2>/dev/null || true
    exit 1
fi

# ── Step 4: Push to registry (optional) ──────────────────────────

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

# ── Step 5: Prune old golden images ──────────────────────────────

log "--- Pruning old golden images (keeping newest ${KEEP_COUNT}) ---"

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

# ── Step 6: Summary ──────────────────────────────────────────────

log "=== Golden Image Refresh Complete ==="
log "Tag:        ${IMAGE_NAME}:${FULL_TAG}"
log "Plugins:    ${PLUGIN_COUNT} (${tool_ids})"
log "Size:       ${IMAGE_SIZE_MB} MB"
log "Build time: ${BUILD_DURATION}s"
if [[ "$PUSH" == "true" ]]; then
    log "Registry:   ${REGISTRY}/${IMAGE_NAME}:${FULL_TAG}"
fi
