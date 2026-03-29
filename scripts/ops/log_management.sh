#!/usr/bin/env bash
# Log Management
# Usage: ./scripts/ops/log_management.sh <command>
set -euo pipefail

usage() {
    cat <<EOF
Spectra Log Management

Usage: $0 <command>

Commands:
  tail [service]      Tail logs for a service (default: app). Services: app, worker, scheduler, ai-svc, db, caddy, minio
  errors [service]    Show recent ERROR lines for a service (default: all)
  export <dir>        Export all service logs to a directory
  sizes               Show log file and container log sizes
EOF
}

SERVICES="spectra-app spectra-worker spectra-scheduler spectra-ai-svc spectra-db spectra-caddy spectra-minio"

case "${1:-}" in
    tail)
        SVC="${2:-app}"
        docker logs -f --tail 100 "spectra-${SVC}" 2>&1
        ;;
    errors)
        SVC="${2:-}"
        if [[ -n "$SVC" ]]; then
            echo "=== Errors in spectra-${SVC} ==="
            docker logs "spectra-${SVC}" 2>&1 | grep -i "error\|exception\|traceback\|critical" | tail -50
        else
            for svc in $SERVICES; do
                COUNT=$(docker logs "$svc" 2>&1 | grep -ci "error\|exception\|critical" || true)
                if [[ "$COUNT" -gt 0 ]]; then
                    echo "=== $svc ($COUNT errors) ==="
                    docker logs "$svc" 2>&1 | grep -i "error\|exception\|critical" | tail -10
                    echo ""
                fi
            done
        fi
        ;;
    export)
        [[ -z "${2:-}" ]] && echo "Usage: $0 export <directory>" && exit 1
        EXPORT_DIR="$2"
        mkdir -p "$EXPORT_DIR"
        TIMESTAMP=$(date -u '+%Y%m%d_%H%M%S')
        for svc in $SERVICES; do
            docker logs "$svc" > "$EXPORT_DIR/${svc}_${TIMESTAMP}.log" 2>&1 || true
        done
        echo "Logs exported to $EXPORT_DIR/"
        ls -lh "$EXPORT_DIR/"
        ;;
    sizes)
        echo "Container log sizes:"
        for svc in $SERVICES; do
            LOG_FILE=$(docker inspect --format='{{.LogPath}}' "$svc" 2>/dev/null || echo "N/A")
            if [[ "$LOG_FILE" != "N/A" && -f "$LOG_FILE" ]]; then
                SIZE=$(du -h "$LOG_FILE" | cut -f1)
                echo "  $svc: $SIZE"
            else
                echo "  $svc: unknown"
            fi
        done
        ;;
    *)
        usage
        ;;
esac
