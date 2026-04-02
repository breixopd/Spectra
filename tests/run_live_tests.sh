#!/usr/bin/env bash
# Run live integration tests against vulnerable containers.
#
# Two modes:
#   1. Full LLM tests:   requires LLM_API_KEY set in .env.test
#   2. Target-only tests: runs scan/vuln tests against lightweight targets
#
# Usage:
#   ./tests/run_live_tests.sh              # Full suite (needs LLM_API_KEY in .env.test)
#   ./tests/run_live_tests.sh --targets    # Target-only (no LLM needed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_BASE="docker/docker-compose.test.yml"
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
    # Full mode — check .env.test for LLM credentials
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env.test"
    if [ -z "${LLM_API_KEY:-}" ] || [ "$LLM_API_KEY" = "your-api-key-here" ]; then
        echo "SKIP: LLM_API_KEY is not configured in .env.test."
        echo "  Add your LLM_API_KEY to .env.test and re-run."
        echo "  Or run with --targets for target-only tests."
        exit 0
    fi
    COMPOSE="docker compose -f $COMPOSE_BASE --profile targets --env-file .env.test"
fi

echo "=== Spectra Live Integration Tests ==="
echo "  Mode:     $([ "$TARGETS_ONLY" = true ] && echo 'targets-only' || echo 'full (LLM)')"
echo ""

export OPS_DB_NAME="spectra_test"
export OPS_DB_USER="spectra"
export OPS_GARAGE_ADMIN_URL="http://127.0.0.1:3903"
export REDACTED_SECRET_ace410934cec
export OREDACTED_SECRET_9044371ec359
export GARAGE_ACCESS_KEY="${OPS_GARAGE_ACCESS_KEY}"
export GARAGE_SECRET_KEY="${OPS_GARAGE_SECRET_KEY}"

bootstrap_garage() {
    local garage_container=""

    garage_container="$($COMPOSE ps -q garage)"
    if [ -z "$garage_container" ]; then
        echo "ERROR: could not resolve Garage container id" >&2
        exit 1
    fi

    GARAGE_CONTAINER="$garage_container" \
    GARAGE_ACCESS_KEY="$OPS_GARAGE_ACCESS_KEY" \
    GARAGE_SECRET_KEY="$OPS_GARAGE_SECRET_KEY" \
    bash ./docker/garage-init.sh
}

wait_for_tools_worker_ready() {
    local tools_container=""
    local pending_install_jobs=""

    tools_container="$($COMPOSE ps -q tools)"
    if [ -z "$tools_container" ]; then
        echo "ERROR: could not resolve tools container id" >&2
        exit 1
    fi

    echo "Waiting for tools worker startup queue to settle..."
    for i in $(seq 1 90); do
        if ! docker inspect --format='{{.State.Running}}' "$tools_container" 2>/dev/null | grep -q true; then
            sleep 1
            continue
        fi

        pending_install_jobs="$($COMPOSE exec -T db psql -U spectra -d spectra_test -P pager=off -A -t -c "select count(*) from job_queue where queue_name = 'default' and function = 'install_all_tools_job' and status in ('queued', 'pending', 'in_progress');" 2>/dev/null | tr -d '[:space:]')"
        if [ "$pending_install_jobs" = "0" ]; then
            echo "Tools worker queue is ready (attempt $i)!"
            return
        fi
        sleep 1
    done

    echo "ERROR: tools worker startup queue did not settle" >&2
    $COMPOSE logs --tail=80 tools >&2 || true
    exit 1
}

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
    $COMPOSE up -d --build db redis garage vuln-web vuln-ssh vuln-network
else
    $COMPOSE up -d --build db redis garage metasploitable dvwa vuln-web vuln-ssh vuln-network
fi

bootstrap_garage

$COMPOSE up -d --build app app-replica caddy tools

# ── Step 2: Wait for health checks ──────────────────────────
echo "Waiting for app to be ready..."
for i in $(seq 1 90); do
    if curl -sf http://localhost:15000/api/health > /dev/null 2>&1; then
        echo "App is ready (attempt $i)!"
        break
    fi
    sleep 2
done

curl -sf http://localhost:15000/api/health > /dev/null || {
    echo "ERROR: test app did not become ready at http://localhost:15000"
    $COMPOSE logs --tail=40 app
    exit 1
}

wait_for_tools_worker_ready

echo "Waiting for vulnerable targets to be healthy..."
for target in spectra-vuln-web spectra-vuln-ssh spectra-vuln-network; do
    target_healthy=false
    for i in $(seq 1 30); do
        if docker inspect --format='{{.State.Health.Status}}' "$target" 2>/dev/null | grep -q healthy; then
            echo "  $target: healthy"
            target_healthy=true
            break
        fi
        sleep 1
    done

    if [ "${target_healthy}" != true ]; then
        target_status="$(docker inspect --format='{{.State.Health.Status}}' "$target" 2>/dev/null || echo 'missing')"
        echo "ERROR: ${target} did not become healthy after 30 seconds (last status: ${target_status})" >&2
        exit 1
    fi
done

# ── Step 3: Run integration tests ───────────────────────────
echo ""
echo "Running live integration tests..."

if [ "$TARGETS_ONLY" = true ]; then
    # Run only the target-scan tests
    $COMPOSE run --rm --no-deps --entrypoint sh test-runner -c \
        "pip install -q pytest pytest-asyncio pytest-dotenv pytest-timeout httpx aiohttp aiosqlite && \
         python3 -m pytest tests/integration/test_live_scan.py -v -m live --timeout=120 --tb=short"
else
    # Full suite: LLM + target tests
    $COMPOSE run --rm --no-deps --entrypoint sh test-runner -c \
        "pip install -q pytest pytest-asyncio pytest-dotenv pytest-timeout httpx aiohttp aiosqlite && \
         python3 -m pytest tests/integration/test_live_targets.py tests/integration/test_live_scan.py -v --timeout=600 --tb=short"
fi

OPS_DB_CONTAINER="$($COMPOSE ps -q db)"
OPS_APP_CONTAINER="$($COMPOSE ps -q app)"
OPS_GARAGE_CONTAINER="$($COMPOSE ps -q garage)"
export OPS_DB_CONTAINER OPS_APP_CONTAINER OPS_GARAGE_CONTAINER

echo ""
echo "Preparing S3 buckets for read-only ops smoke tests..."
GARAGE_CONTAINER="${OPS_GARAGE_CONTAINER}" \
GARAGE_ADMIN_URL="${OPS_GARAGE_ADMIN_URL}" \
GARAGE_ACCESS_KEY="${OPS_GARAGE_ACCESS_KEY}" \
GARAGE_SECRET_KEY="${OPS_GARAGE_SECRET_KEY}" \
./scripts/ops/s3_management.sh create-buckets >/dev/null

echo "Running live ops smoke tests..."
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest "${OPS_TEST_FILE}" -v -m live --tb=short --override-ini=addopts=

# ── Step 4: Collect results ──────────────────────────────────
echo ""
echo "=== Live tests complete ==="
