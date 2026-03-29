#!/usr/bin/env bash
# S3/MinIO Storage Management
# Usage: ./scripts/ops/s3_management.sh <command>
set -euo pipefail

MINIO_CONTAINER="${MINIO_CONTAINER:-spectra-minio}"
MINIO_ALIAS="${MINIO_ALIAS:-spectra}"
MINIO_URL="${MINIO_URL:-http://localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ROOT_USER:-${S3_ACCESS_KEY:-}}"
MINIO_SECRET_KEY="${MINIO_ROOT_PASSWORD:-${S3_SECRET_KEY:-}}"

urlencode() {
    python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))'
}

validate_minio_url() {
    if ! printf '%s' "${MINIO_URL}" | python3 -c '
import sys
from urllib.parse import urlsplit

url = sys.stdin.read().strip()
parts = urlsplit(url)

if parts.scheme not in {"http", "https"}:
    raise SystemExit("MINIO_URL must start with http:// or https://")
if not parts.hostname:
    raise SystemExit("MINIO_URL must include a hostname")
if parts.username is not None or parts.password is not None:
    raise SystemExit("MINIO_URL must not contain embedded credentials")
try:
    _ = parts.port
except ValueError:
    raise SystemExit("MINIO_URL has an invalid port")
if parts.query:
    raise SystemExit("MINIO_URL must not contain a query string")
if parts.fragment:
    raise SystemExit("MINIO_URL must not contain a fragment")
if parts.path not in {"", "/"}:
    raise SystemExit("MINIO_URL must not contain a path")
'; then
        exit 1
    fi
}

require_creds() {
    if [[ -z "${MINIO_ACCESS_KEY}" || -z "${MINIO_SECRET_KEY}" ]]; then
        echo "MINIO_ROOT_USER/S3_ACCESS_KEY and MINIO_ROOT_PASSWORD/S3_SECRET_KEY must be set" >&2
        exit 1
    fi
}

mc_cmd() {
    local encoded_access_key encoded_secret_key

    require_creds
    validate_minio_url
    encoded_access_key="$(printf '%s' "${MINIO_ACCESS_KEY}" | urlencode)"
    encoded_secret_key="$(printf '%s' "${MINIO_SECRET_KEY}" | urlencode)"

    printf '%s\n%s\n' "${encoded_access_key}" "${encoded_secret_key}" | \
        docker exec -i "${MINIO_CONTAINER}" sh -c '
            IFS= read -r encoded_access_key
            IFS= read -r encoded_secret_key
            alias_name="$1"
            url="$2"
            shift 2

            case "${url}" in
                http://*)
                    cred_url="http://${encoded_access_key}:${encoded_secret_key}@${url#http://}"
                    ;;
                https://*)
                    cred_url="https://${encoded_access_key}:${encoded_secret_key}@${url#https://}"
                    ;;
                *)
                    echo "Unsupported MinIO URL scheme: ${url}" >&2
                    exit 1
                    ;;
            esac

            mc_host_var="MC_HOST_${alias_name}"
            export "${mc_host_var}=${cred_url}"
            exec mc "$@"
        ' sh "${MINIO_ALIAS}" "${MINIO_URL}" "$@"
}

usage() {
    cat <<EOF
Spectra S3/MinIO Storage Management

Usage: $0 <command>

Commands:
  status                    Show MinIO service status and disk usage
  buckets                   List all buckets with sizes
  list <bucket> [prefix]    List objects in a bucket
  usage                     Show total storage usage per bucket
  create-buckets            Create all required Spectra buckets
  health                    Check MinIO health
EOF
}

case "${1:-}" in
    status)
        echo "MinIO service info:"
        mc_cmd admin info "${MINIO_ALIAS}"
        ;;
    buckets)
        echo "Buckets:"
        mc_cmd ls "$MINIO_ALIAS/"
        ;;
    list)
        BUCKET="${2:-}"
        PREFIX="${3:-}"
        [[ -z "${BUCKET}" ]] && echo "Usage: ${0} list <bucket> [prefix]" && exit 1
        mc_cmd ls "${MINIO_ALIAS}/${BUCKET}/${PREFIX}"
        ;;
    usage)
        echo "Storage usage by bucket:"
        for bucket in spectra-missions spectra-sessions spectra-knowledge spectra-backups; do
            SIZE="$(mc_cmd du "${MINIO_ALIAS}/${bucket}" | tail -1)"
            echo "  ${bucket}: ${SIZE}"
        done
        ;;
    create-buckets)
        echo "Creating required buckets..."
        for bucket in spectra-missions spectra-sessions spectra-knowledge spectra-backups; do
            mc_cmd mb --ignore-existing "${MINIO_ALIAS}/${bucket}"
            echo "  ✓ ${bucket}"
        done
        echo "Done."
        ;;
    health)
        local_health_url=""

        validate_minio_url
        local_health_url="${MINIO_URL%/}/minio/health/live"

        echo "MinIO health:"
        if curl -sf "${local_health_url}"; then
            echo " OK"
        else
            echo " UNHEALTHY" >&2
            exit 1
        fi
        ;;
    *)
        usage >&2
        exit 1
        ;;
esac
