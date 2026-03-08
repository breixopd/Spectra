#!/usr/bin/env bash
# Run live integration tests through docker compose only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="docker/docker-compose.test.yml"

cd "$PROJECT_DIR"

echo "=== Spectra Live Integration Tests ==="
echo "Compose file: $COMPOSE_FILE"
echo ""

echo "Starting live-test services..."
docker compose -f "$COMPOSE_FILE" up -d db tools metasploitable dvwa app

echo "Waiting for app to be ready..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:5000/api/health > /dev/null 2>&1; then
        echo "App is ready!"
        break
    fi
    sleep 2
done

curl -sf http://localhost:5000/api/health > /dev/null || {
    echo "ERROR: test app did not become ready at http://localhost:5000"
    exit 1
}

echo ""
echo "Running tests..."
docker compose -f "$COMPOSE_FILE" run --rm test-runner \
    tests/integration/test_live_targets.py -v --timeout=300 --tb=short "$@"
