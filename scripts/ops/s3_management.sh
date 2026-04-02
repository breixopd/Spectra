#!/usr/bin/env bash
# S3/Garage Storage Management
# Usage: ./scripts/ops/s3_management.sh <command>
set -euo pipefail

GARAGE_CONTAINER="${GARAGE_CONTAINER:-spectra-garage}"
GARAGE_ADMIN_URL="${GARAGE_ADMIN_URL:-http://localhost:3903}"
GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-${S3_ACCESS_KEY:-}}"
GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-${S3_SECRET_KEY:-}}"

validate_garage_url() {
    if ! printf '%s' "${GARAGE_ADMIN_URL}" | python3 -c '
import sys
from urllib.parse import urlsplit

url = sys.stdin.read().strip()
parts = urlsplit(url)

if parts.scheme not in {"http", "https"}:
    raise SystemExit("GARAGE_ADMIN_URL must start with http:// or https://")
if not parts.hostname:
    raise SystemExit("GARAGE_ADMIN_URL must include a hostname")
if parts.username is not None or parts.password is not None:
    raise SystemExit("GARAGE_ADMIN_URL must not contain embedded credentials")
try:
    _ = parts.port
except ValueError:
    raise SystemExit("GARAGE_ADMIN_URL has an invalid port")
if parts.query:
    raise SystemExit("GARAGE_ADMIN_URL must not contain a query string")
if parts.fragment:
    raise SystemExit("GARAGE_ADMIN_URL must not contain a fragment")
if parts.path not in {"", "/"}:
    raise SystemExit("GARAGE_ADMIN_URL must not contain a path")
'; then
        exit 1
    fi
}

require_creds() {
    if [[ -z "${GARAGE_ACCESS_KEY}" || -z "${GARAGE_SECRET_KEY}" ]]; then
        echo "GARAGE_ACCESS_KEY and GARAGE_SECRET_KEY must be set" >&2
        exit 1
    fi
}

garage_cmd() {
    docker exec "${GARAGE_CONTAINER}" /garage "$@"
}

usage() {
    cat <<EOF
Spectra S3/Garage Storage Management

Usage: $0 <command>

Commands:
  status                    Show Garage service status
  buckets                   List all buckets
  list <bucket> [prefix]    List objects in a bucket (via garage CLI)
  usage                     Show total storage usage per bucket
  create-buckets            Create all required Spectra buckets
  health                    Check Garage health
EOF
}

case "${1:-}" in
    status)
        echo "Garage service info:"
        garage_cmd status
        ;;
    buckets)
        echo "Buckets:"
        garage_cmd bucket list
        ;;
    list)
        BUCKET="${2:-}"
        PREFIX="${3:-}"
        [[ -z "${BUCKET}" ]] && echo "Usage: ${0} list <bucket> [prefix]" && exit 1
        require_creds
        echo "Objects in ${BUCKET}/${PREFIX}:"
        garage_cmd bucket info "${BUCKET}"
        ;;
    usage)
        echo "Storage usage by bucket:"
        for bucket in spectra-missions spectra-sessions spectra-knowledge spectra-backups; do
            echo "  ${bucket}:"
            garage_cmd bucket info "${bucket}" 2>/dev/null || echo "    (not found)"
        done
        ;;
    create-buckets)
        echo "Creating required buckets..."
        require_creds
        for bucket in spectra-missions spectra-sessions spectra-knowledge spectra-backups; do
            garage_cmd bucket create "${bucket}" 2>/dev/null || true
            echo "  ✓ ${bucket}"
        done
        echo "Done."
        ;;
    health)
        echo "Garage health:"
        if garage_cmd status >/dev/null 2>&1; then
            echo "OK"
        else
            echo "UNHEALTHY" >&2
            exit 1
        fi
        ;;
    *)
        usage >&2
        exit 1
        ;;
esac
