#!/usr/bin/env bash
# Run live integration tests with a real LLM provider against vulnerable containers.
# Requires .env.live with valid API credentials (copy from .env.live.example).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_BASE="docker/docker-compose.test.yml"
COMPOSE_LIVE="docker/docker-compose.live.yml"
ENV_LIVE="$PROJECT_DIR/.env.live"

cd "$PROJECT_DIR"

# --- Pre-flight: check .env.live exists ---
if [ ! -f "$ENV_LIVE" ]; then
    echo "SKIP: .env.live not found."
    echo "  Copy .env.live.example to .env.live and fill in your LLM credentials."
    echo "  cp .env.live.example .env.live"
    exit 0
fi

# --- Pre-flight: check LLM_API_KEY is set ---
# shellcheck disable=SC1090
source "$ENV_LIVE"
if [ -z "${LLM_API_KEY:-}" ] || [ "$LLM_API_KEY" = "your-api-key-here" ]; then
    echo "SKIP: LLM_API_KEY is not configured in .env.live."
    echo "  Set a valid API key to run live LLM integration tests."
    exit 0
fi

COMPOSE="docker compose -f $COMPOSE_BASE -f $COMPOSE_LIVE"

echo "=== Spectra Live Integration Tests (real LLM) ==="
echo "  Base:     $COMPOSE_BASE"
echo "  Override: $COMPOSE_LIVE"
echo "  Provider: ${AI_PROVIDER:-litellm}"
echo "  Model:    ${LLM_MODEL:-unset}"
echo ""

cleanup() {
    echo ""
    echo "=== App container logs ==="
    $COMPOSE logs --tail=80 app 2>/dev/null || true
    echo ""
    echo "Tearing down services..."
    $COMPOSE down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo "Starting live-test services..."
$COMPOSE up -d db tools metasploitable dvwa app

echo "Waiting for app to be ready..."
for i in $(seq 1 90); do
    if curl -sf http://localhost:5000/api/health > /dev/null 2>&1; then
        echo "App is ready!"
        break
    fi
    sleep 2
done

curl -sf http://localhost:5000/api/health > /dev/null || {
    echo "ERROR: test app did not become ready at http://localhost:5000"
    $COMPOSE logs --tail=40 app
    exit 1
}

echo ""
echo "Running live integration tests (timeout 600s per test)..."
$COMPOSE run --rm --entrypoint sh test-runner -c \
    "pip install -q pytest pytest-asyncio pytest-dotenv pytest-timeout httpx aiohttp aiosqlite && python3 -m pytest tests/integration/test_live_targets.py -v --timeout=600 --tb=short"
