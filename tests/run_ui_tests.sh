#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="deploy/docker/compose.yaml"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-spectra-ui-tests}"
export SPECTRA_CONTAINER_PREFIX="${SPECTRA_CONTAINER_PREFIX:-spectra-ui-tests-}"
export GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}"
export GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}"
# Test credentials are deterministic fixtures; keep their values out of local and CI logs.
export GARAGE_PRINT_CREDENTIALS="${GARAGE_PRINT_CREDENTIALS:-0}"

cleanup() {
    echo ""
    echo "Cleaning up test environment..."
    docker compose -f "$COMPOSE_FILE" --profile app --profile test down -v --remove-orphans 2>/dev/null || true
}

trap cleanup EXIT

echo "=== Spectra UI Tests ==="
echo "Resetting test environment..."

cd "$PROJECT_DIR"

# Match integration/e2e: use .env.test for compose env_file so RATE_LIMIT_*, API keys, etc. apply.
if [[ -f "$PROJECT_DIR/.env.test" ]]; then
  export ENV_FILE="$PROJECT_DIR/.env.test"
fi

docker compose -f "$COMPOSE_FILE" --profile app --profile test down -v --remove-orphans 2>/dev/null || true

echo "Starting test environment..."

# Start prerequisites and bootstrap Garage before app startup
docker compose -f "$COMPOSE_FILE" up -d --force-recreate db redis garage

GARAGE_CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps -q garage)"
GARAGE_CONTAINER="$GARAGE_CONTAINER" \
GARAGE_ACCESS_KEY="$GARAGE_ACCESS_KEY" \
GARAGE_SECRET_KEY="$GARAGE_SECRET_KEY" \
bash ./deploy/docker/garage-init.sh

docker compose -f "$COMPOSE_FILE" --profile app build app
docker compose -f "$COMPOSE_FILE" --profile app up -d --force-recreate app

# Wait for app to be ready
echo "Waiting for app to be ready..."
for i in $(seq 1 30); do
    if docker compose -f "$COMPOSE_FILE" exec -T app python3 -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/healthz', timeout=5); sys.exit(0)" > /dev/null 2>&1; then
        echo "App is ready!"
        break
    fi
    sleep 2
done

if ! docker compose -f "$COMPOSE_FILE" exec -T app python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/healthz', timeout=5)" > /dev/null 2>&1; then
    echo "ERROR: app did not become ready" >&2
    docker compose -f "$COMPOSE_FILE" logs --tail=80 app >&2 || true
    exit 1
fi

# Run setup if needed
echo "Setting up test user..."
docker compose -f "$COMPOSE_FILE" exec -T app python3 -c "import json, sys, urllib.error, urllib.request; req = urllib.request.Request('http://127.0.0.1:5000/api/v1/auth/setup', data=json.dumps({'user': {'username': 'admin', 'email': 'admin@test.com', 'password': 'TestPassword123!'}, 'provider_profiles': {'default': {'provider': 'mock', 'model': 'mock'}}, 'provider_routing': {'default': 'default'}, 'provider_fallbacks': {'default': []}}).encode(), headers={'Content-Type': 'application/json'}); 
try:
    urllib.request.urlopen(req, timeout=10)
    print('Setup completed.')
except urllib.error.HTTPError as exc:
    if exc.code in {403, 409}:
        print('Already set up; continuing.')
        sys.exit(0)
    raise" \
    || { echo "ERROR: test-user setup failed" >&2; exit 1; }

# Run Playwright tests
echo "Running UI tests..."
docker compose -f "${COMPOSE_FILE}" --profile test build ui-test-runner
# Chromium's HTTPS-first policy upgrades the single-label `app` hostname to TLS.
# The prefixed compose container alias avoids that upgrade while keeping each
# worktree isolated on its private Docker network.
docker compose -f "${COMPOSE_FILE}" --profile test run --rm -e "APP_BASE_URL=http://${SPECTRA_CONTAINER_PREFIX}app:5000" ui-test-runner tests/e2e/ui/test_spa_workspace.py -v --tb=short -x -p no:cov --confcutdir=tests/e2e/ui --override-ini=addopts= "$@"

echo "=== Done ==="
