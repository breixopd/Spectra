#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="docker/docker-compose.test.yml"
export GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}"
export GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}"

cleanup() {
    echo ""
    echo "Cleaning up test environment..."
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
}

trap cleanup EXIT

echo "=== Spectra UI Tests ==="
echo "Resetting test environment..."

cd "$PROJECT_DIR"

docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true

echo "Starting test environment..."

# Start prerequisites and bootstrap Garage before app startup
docker compose -f "$COMPOSE_FILE" up -d --force-recreate db redis garage

GARAGE_CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps -q garage)"
GARAGE_CONTAINER="$GARAGE_CONTAINER" \
GARAGE_ACCESS_KEY="$GARAGE_ACCESS_KEY" \
GARAGE_SECRET_KEY="$GARAGE_SECRET_KEY" \
bash ./docker/garage-init.sh

docker compose -f "$COMPOSE_FILE" build app
docker compose -f "$COMPOSE_FILE" up -d --force-recreate app

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
docker compose -f "${COMPOSE_FILE}" build ui-test-runner
docker compose -f "${COMPOSE_FILE}" run --rm -e APP_BASE_URL=http://host.docker.internal:15000 ui-test-runner tests/e2e/ui/ -v --tb=short -x --no-cov --confcutdir=tests/e2e/ui --override-ini=addopts= "$@"

echo "=== Done ==="
