#!/bin/bash
# Scale Spectra services dynamically.
#
# Usage:
#   ./scripts/scale.sh [service] [count]
#
# Examples:
#   ./scripts/scale.sh spectra-app 5    # Scale app to 5 replicas
#   ./scripts/scale.sh spectra-tools 3  # Scale tools to 3 workers
#   ./scripts/scale.sh worker 4         # Scale background workers

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_PROD="docker/docker-compose.prod.yml"
COMPOSE_SCALE="docker/docker-compose.scale.yml"

SERVICE="${1:-}"
COUNT="${2:-}"

usage() {
    echo "Usage: $0 <service> <count>"
    echo ""
    echo "Services:"
    echo "  app       Spectra API (FastAPI)       default: 3"
    echo "  tools     Security tool workers       default: 2"
    echo "  worker    Background job workers      default: 2"
    echo ""
    echo "Examples:"
    echo "  $0 app 5"
    echo "  $0 tools 3"
    exit 1
}

if [ -z "$SERVICE" ] || [ -z "$COUNT" ]; then
    usage
fi

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [ "$COUNT" -lt 1 ] || [ "$COUNT" -gt 20 ]; then
    echo "ERROR: count must be a number between 1 and 20"
    exit 1
fi

cd "$PROJECT_DIR"

COMPOSE_CMD="docker compose -f $COMPOSE_PROD -f $COMPOSE_SCALE"

echo "Scaling $SERVICE to $COUNT replicas..."
$COMPOSE_CMD up -d --scale "$SERVICE=$COUNT" --no-recreate

echo ""
echo "Current replica counts:"
$COMPOSE_CMD ps --format "table {{.Service}}\t{{.State}}\t{{.Ports}}" | head -30

echo ""
echo "Done. $SERVICE scaled to $COUNT replicas."
