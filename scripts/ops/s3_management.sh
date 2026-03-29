#!/usr/bin/env bash
# S3/MinIO Storage Management
# Usage: ./scripts/ops/s3_management.sh <command>
set -euo pipefail

MINIO_CONTAINER="${MINIO_CONTAINER:-spectra-minio}"
MINIO_ALIAS="${MINIO_ALIAS:-spectra}"

# Set up mc alias if inside container
setup_mc() {
    docker exec "$MINIO_CONTAINER" mc alias set "$MINIO_ALIAS" \
        "http://localhost:9000" \
        "${S3_ACCESS_KEY:-minioadmin}" \
        "${S3_SECRET_KEY:-minioadmin}" 2>/dev/null || true
}

mc_cmd() {
    docker exec "$MINIO_CONTAINER" mc "$@"
}

usage() {
    cat <<EOF
Spectra S3/MinIO Storage Management

Usage: $0 <command>

Commands:
  status              Show MinIO service status and disk usage
  buckets             List all buckets with sizes
  list <bucket> [prefix]  List objects in a bucket
  usage               Show total storage usage per bucket
  create-buckets      Create all required Spectra buckets
  health              Check MinIO health
EOF
}

case "${1:-}" in
    status)
        setup_mc
        echo "MinIO service info:"
        mc_cmd admin info "$MINIO_ALIAS" 2>/dev/null || echo "Cannot reach MinIO admin API"
        ;;
    buckets)
        setup_mc
        echo "Buckets:"
        mc_cmd ls "$MINIO_ALIAS/"
        ;;
    list)
        setup_mc
        BUCKET="${2:-}"
        PREFIX="${3:-}"
        [[ -z "$BUCKET" ]] && echo "Usage: $0 list <bucket> [prefix]" && exit 1
        mc_cmd ls "$MINIO_ALIAS/$BUCKET/$PREFIX"
        ;;
    usage)
        setup_mc
        echo "Storage usage by bucket:"
        for bucket in spectra-missions spectra-sessions spectra-knowledge spectra-backups; do
            SIZE=$(mc_cmd du "$MINIO_ALIAS/$bucket" 2>/dev/null | tail -1 || echo "N/A")
            echo "  $bucket: $SIZE"
        done
        ;;
    create-buckets)
        setup_mc
        echo "Creating required buckets..."
        for bucket in spectra-missions spectra-sessions spectra-knowledge spectra-backups; do
            mc_cmd mb --ignore-existing "$MINIO_ALIAS/$bucket"
            echo "  ✓ $bucket"
        done
        echo "Done."
        ;;
    health)
        echo "MinIO health:"
        docker exec "$MINIO_CONTAINER" curl -sf http://localhost:9000/minio/health/live && echo " OK" || echo " UNHEALTHY"
        ;;
    *)
        usage
        ;;
esac
