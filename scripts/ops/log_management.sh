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

SERVICES=(app worker scheduler ai-svc db caddy minio)

_container_name_for_service() {
    local service="${1}"

    case "${service}" in
        app)
            printf '%s\n' "${APP_CONTAINER:-spectra-app}"
            ;;
        worker)
            printf '%s\n' "${WORKER_CONTAINER:-spectra-worker}"
            ;;
        scheduler)
            printf '%s\n' "${SCHEDULER_CONTAINER:-spectra-scheduler}"
            ;;
        ai-svc)
            printf '%s\n' "${AI_CONTAINER:-spectra-ai}"
            ;;
        db)
            printf '%s\n' "${DB_CONTAINER:-spectra-db}"
            ;;
        caddy)
            printf '%s\n' "${CADDY_CONTAINER:-spectra-caddy}"
            ;;
        minio)
            printf '%s\n' "${MINIO_CONTAINER:-spectra-minio}"
            ;;
        *)
            echo "Unknown service: ${service}" >&2
            echo "Valid services: ${SERVICES[*]}" >&2
            exit 1
            ;;
    esac
}

case "${1:-}" in
    tail)
        SVC="${2:-app}"
        CONTAINER_NAME="$(_container_name_for_service "${SVC}")"
        docker logs -f --tail 100 "${CONTAINER_NAME}" 2>&1
        ;;
    errors)
        SVC="${2:-}"
        if [[ -n "${SVC}" ]]; then
            CONTAINER_NAME="$(_container_name_for_service "${SVC}")"
            echo "=== Errors in ${CONTAINER_NAME} ==="
            docker logs "${CONTAINER_NAME}" 2>&1 | grep -i "error\|exception\|traceback\|critical" | tail -50
        else
            for svc in "${SERVICES[@]}"; do
                CONTAINER_NAME="$(_container_name_for_service "${svc}")"
                COUNT=$(docker logs "${CONTAINER_NAME}" 2>&1 | grep -ci "error\|exception\|critical" || true)
                if [[ "${COUNT}" -gt 0 ]]; then
                    echo "=== ${CONTAINER_NAME} (${COUNT} errors) ==="
                    docker logs "${CONTAINER_NAME}" 2>&1 | grep -i "error\|exception\|critical" | tail -10
                    echo ""
                fi
            done
        fi
        ;;
    export)
        [[ -z "${2:-}" ]] && echo "Usage: $0 export <directory>" && exit 1
        EXPORT_DIR="$2"
        mkdir -p "${EXPORT_DIR}"
        TIMESTAMP=$(date -u '+%Y%m%d_%H%M%S')
        for svc in "${SERVICES[@]}"; do
            CONTAINER_NAME="$(_container_name_for_service "${svc}")"
            docker logs "${CONTAINER_NAME}" > "${EXPORT_DIR}/${CONTAINER_NAME}_${TIMESTAMP}.log" 2>&1 || true
        done
        echo "Logs exported to ${EXPORT_DIR}/"
        ls -lh "${EXPORT_DIR}/"
        ;;
    sizes)
        echo "Container log sizes:"
        for svc in "${SERVICES[@]}"; do
            CONTAINER_NAME="$(_container_name_for_service "${svc}")"
            LOG_FILE=$(docker inspect --format='{{.LogPath}}' "${CONTAINER_NAME}" 2>/dev/null || echo "N/A")
            if [[ "${LOG_FILE}" != "N/A" && -f "${LOG_FILE}" ]]; then
                SIZE=$(du -h "${LOG_FILE}" | cut -f1)
                echo "  ${CONTAINER_NAME}: ${SIZE}"
            else
                echo "  ${CONTAINER_NAME}: unknown"
            fi
        done
        ;;
    *)
        usage
        ;;
esac
