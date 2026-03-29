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
ENV_LIVE="$PROJECT_DIR/.env.live"
OPS_TEST_FILE="tests/integration/test_ops_scripts_live.py"

cd "$PROJECT_DIR"

TARGETS_ONLY=false
if [ "${1:-}" = "--targets" ]; then
    TARGETS_ONLY=true
fi

# ── Compose commands ──────────────────────────────────────────
# Targets are in the test compose behind --profile targets
COMPOSE_TARGETS="docker compose -f $COMPOSE_BASE --profile targets"

if [ "$TARGETS_ONLY" = true ]; then
    COMPOSE="docker compose -f $COMPOSE_BASE --profile targets"
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
    COMPOSE="docker compose -f $COMPOSE_BASE --profile targets --env-file .env.live"
fi

echo "=== Spectra Live Integration Tests ==="
echo "  Mode:     $([ "$TARGETS_ONLY" = true ] && echo 'targets-only' || echo 'full (LLM)')"
echo ""

export OPS_DB_NAME="spectra_test"
export OPS_DB_USER="spectra"
export OPS_MINIO_URL="http://127.0.0.1:19000"
export OPS_MINIO_ROOT_USER="spectra"
export OPS_MINIO_ROOT_PASSWORD="spectra_test_minio"

cleanup() {
    echo ""
    echo "=== Collecting logs ==="
    $COMPOSE logs --tail=40 app 2>/dev/null || true
    echo ""
    echo "Tearing down services..."
    $COMPOSE down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# ── Step 1: Start all services (including targets via profile) ─
echo "Starting Spectra services and vulnerable targets..."
if [ "$TARGETS_ONLY" = true ]; then
    $COMPOSE up -d --build db minio app tools vuln-web vuln-ssh vuln-network
else
    $COMPOSE up -d --build db minio tools metasploitable dvwa app vuln-web vuln-ssh vuln-network
fi

# ── Step 2: Wait for health checks ──────────────────────────
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

# ── Step 3: Run integration tests ───────────────────────────
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

OPS_DB_CONTAINER="$($COMPOSE ps -q db)"
OPS_APP_CONTAINER="$($COMPOSE ps -q app)"
OPS_MINIO_CONTAINER="$($COMPOSE ps -q minio)"
export OPS_DB_CONTAINER OPS_APP_CONTAINER OPS_MINIO_CONTAINER

echo ""
echo "Preparing S3 buckets for read-only ops smoke tests..."
MINIO_CONTAINER="${OPS_MINIO_CONTAINER}" \
MINIO_URL="${OPS_MINIO_URL}" \
MINIO_ROOT_USER="${OPS_MINIO_ROOT_USER}" \
MINIO_ROOT_PASSWORD="${OPS_MINIO_ROOT_PASSWORD}" \
./scripts/ops/s3_management.sh create-buckets >/dev/null

echo "Running live ops smoke tests..."
python3 -m pytest "${OPS_TEST_FILE}" -v -m live --tb=short --override-ini=addopts=

# ── Step 4: Collect results ──────────────────────────────────
echo ""
echo "=== Live tests complete ==="
