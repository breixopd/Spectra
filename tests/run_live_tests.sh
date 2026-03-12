#!/usr/bin/env bash
# Run live integration tests against vulnerable containers.
#
# Two modes:
#   1. Full LLM tests:   requires .env.live with valid API credentials
#   2. Target-only tests: runs scan/vuln tests against lightweight targets
#
# Usage:
#   ./tests/run_live_tests.sh              # Full suite (needs .env.live)
#   ./tests/run_live_tests.sh --targets    # Target-only (no LLM needed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_BASE="docker/docker-compose.test.yml"
COMPOSE_LIVE="docker/docker-compose.live.yml"
COMPOSE_TARGETS="docker/docker-compose.targets.yml"
ENV_LIVE="$PROJECT_DIR/.env.live"

cd "$PROJECT_DIR"

TARGETS_ONLY=false
if [ "${1:-}" = "--targets" ]; then
    TARGETS_ONLY=true
fi

# ── Ensure spectra-network exists ─────────────────────────────
docker network create spectra-network 2>/dev/null || true

# ── Compose commands ──────────────────────────────────────────
COMPOSE_TARGETS_CMD="docker compose -f $COMPOSE_TARGETS"

if [ "$TARGETS_ONLY" = true ]; then
    COMPOSE="docker compose -f $COMPOSE_BASE"
else
    # Full mode — check .env.live
    if [ ! -f "$ENV_LIVE" ]; then
        echo "SKIP: .env.live not found."
        echo "  Copy .env.live.example to .env.live and fill in your LLM credentials."
        echo "  Or run with --targets for target-only tests."
        exit 0
    fi
    # shellcheck disable=SC1090
    source "$ENV_LIVE"
    if [ -z "${LLM_API_KEY:-}" ] || [ "$LLM_API_KEY" = "your-api-key-here" ]; then
        echo "SKIP: LLM_API_KEY is not configured in .env.live."
        exit 0
    fi
    COMPOSE="docker compose -f $COMPOSE_BASE -f $COMPOSE_LIVE"
fi

echo "=== Spectra Live Integration Tests ==="
echo "  Mode:     $([ "$TARGETS_ONLY" = true ] && echo 'targets-only' || echo 'full (LLM)')"
echo "  Targets:  $COMPOSE_TARGETS"
echo ""

cleanup() {
    echo ""
    echo "=== Collecting logs ==="
    $COMPOSE logs --tail=40 app 2>/dev/null || true
    $COMPOSE_TARGETS_CMD logs --tail=20 2>/dev/null || true
    echo ""
    echo "Tearing down services..."
    $COMPOSE_TARGETS_CMD down -v --remove-orphans 2>/dev/null || true
    $COMPOSE down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# ── Step 1: Build and start vulnerable targets ───────────────
echo "Building vulnerable test targets..."
$COMPOSE_TARGETS_CMD build

echo "Starting vulnerable targets..."
$COMPOSE_TARGETS_CMD up -d

# ── Step 2: Start Spectra infrastructure ─────────────────────
echo "Starting Spectra services..."
if [ "$TARGETS_ONLY" = true ]; then
    $COMPOSE up -d db app tools
else
    $COMPOSE up -d db tools metasploitable dvwa app
fi

# ── Step 3: Wait for health checks ──────────────────────────
echo "Waiting for app to be ready..."
for i in $(seq 1 90); do
    if curl -sf http://localhost:5000/api/health > /dev/null 2>&1; then
        echo "App is ready (attempt $i)!"
        break
    fi
    sleep 2
done

curl -sf http://localhost:5000/api/health > /dev/null || {
    echo "ERROR: test app did not become ready at http://localhost:5000"
    $COMPOSE logs --tail=40 app
    exit 1
}

echo "Waiting for vulnerable targets to be healthy..."
for target in spectra-vuln-web spectra-vuln-ssh spectra-vuln-network; do
    for i in $(seq 1 30); do
        if docker inspect --format='{{.State.Health.Status}}' "$target" 2>/dev/null | grep -q healthy; then
            echo "  $target: healthy"
            break
        fi
        sleep 1
    done
done

# ── Step 4: Run integration tests ───────────────────────────
echo ""
echo "Running live integration tests..."

if [ "$TARGETS_ONLY" = true ]; then
    # Run only the target-scan tests
    $COMPOSE run --rm --entrypoint sh test-runner -c \
        "pip install -q pytest pytest-asyncio pytest-dotenv pytest-timeout httpx aiohttp aiosqlite && \
         python3 -m pytest tests/integration/test_live_scan.py -v -m live --timeout=120 --tb=short"
else
    # Full suite: LLM + target tests
    $COMPOSE run --rm --entrypoint sh test-runner -c \
        "pip install -q pytest pytest-asyncio pytest-dotenv pytest-timeout httpx aiohttp aiosqlite && \
         python3 -m pytest tests/integration/test_live_targets.py tests/integration/test_live_scan.py -v --timeout=600 --tb=short"
fi

# ── Step 5: Collect results ──────────────────────────────────
echo ""
echo "=== Live tests complete ==="
