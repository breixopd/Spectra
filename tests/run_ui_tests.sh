#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker/docker-compose.test.yml"

echo "=== Spectra UI Tests ==="

# Support optional test filter: ./run_ui_tests.sh [additional-args]
echo "Starting test environment..."

cd "$(dirname "$0")/.."

cleanup() {
    echo ""
    echo "Tearing down test services..."
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# Start services
docker compose -f "$COMPOSE_FILE" up -d --force-recreate db app

# Wait for app to be ready
echo "Waiting for app to be ready..."
for i in $(seq 1 30); do
    if docker compose -f "$COMPOSE_FILE" exec -T app python3 -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=5); sys.exit(0)" > /dev/null 2>&1; then
        echo "App is ready!"
        break
    fi
    sleep 2
done

# Run setup if needed
echo "Setting up test user..."
docker compose -f "$COMPOSE_FILE" exec -T app python3 -c "import json, sys, urllib.error, urllib.request; req = urllib.request.Request('http://127.0.0.1:5000/api/auth/setup', data=json.dumps({'user': {'username': 'admin', 'email': 'admin@test.com', 'password': 'TestPassword123!'}, 'provider_profiles': {'default': {'provider': 'mock', 'model': 'mock'}}, 'provider_routing': {'default': 'default'}, 'provider_fallbacks': {'default': []}}).encode(), headers={'Content-Type': 'application/json'}); 
try:
    urllib.request.urlopen(req, timeout=10)
    print('Setup completed.')
except urllib.error.HTTPError as exc:
    if exc.code in {403, 409}:
        print('Already set up; continuing.')
        sys.exit(0)
    raise" \
    || echo "(setup step failed; continuing with existing state)"

# Run Playwright tests
echo "Running UI tests..."
docker compose -f "$COMPOSE_FILE" build ui-test-runner
docker compose -f "$COMPOSE_FILE" run --rm ui-test-runner "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "=== All UI tests PASSED ==="
else
    echo "=== UI tests FAILED (exit code: $EXIT_CODE) ==="
fi
exit $EXIT_CODE
