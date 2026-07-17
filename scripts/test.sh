#!/usr/bin/env bash
# scripts/test.sh — Docker-based test runner for Spectra
#
# All commands run through deploy/docker/compose.yaml test-profile runners,
# matching CI exactly (see .github/workflows/ci.yml).
#
# Usage:
#   ./scripts/test.sh              # Run unit tests (default)
#   ./scripts/test.sh unit         # Run unit tests
#   ./scripts/test.sh integration  # Run integration tests (starts deps)
#   ./scripts/test.sh all          # Run unit + integration
#   ./scripts/test.sh coverage     # Unit tests with coverage gate (CI parity)
#   ./scripts/test.sh load         # Run burst/load tests with the test stack
#   ./scripts/test.sh performance  # Run performance smoke tests with the test stack
#   ./scripts/test.sh soak         # Run soak/stability tests with the test stack
#   ./scripts/test.sh live-smoke   # Run live API/UI/LLM smoke tests
#   ./scripts/test.sh file <path>  # Run a specific test file (unit runner)
#
# Environment:
#   REBUILD=1           Force rebuild the test image before running
#   START_STACK=1       Bring up the app+test stack before live-smoke
#   SPECTRA_KEEP_TEST_ARTIFACTS=1  Export smoke diagnostics to ./reports
#
# Full extended matrix (parity + load/perf/soak + Playwright + live targets; optional LLM live):
#   ./scripts/runbooks/full-test-matrix.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/deploy/docker/compose.yaml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Fresh clones need a .env.test file (compose mounts it; keys stay local and gitignored).
ensure_env_test() {
    if [[ -f "$PROJECT_ROOT/.env.test" ]]; then
        return 0
    fi
    if [[ -f "$PROJECT_ROOT/.env.test.example" ]]; then
        cp "$PROJECT_ROOT/.env.test.example" "$PROJECT_ROOT/.env.test"
        echo -e "${YELLOW}Created .env.test from .env.test.example — add secrets locally; file is gitignored.${NC}"
        return 0
    fi
    echo -e "${RED}Missing $PROJECT_ROOT/.env.test and no .env.test.example to copy.${NC}" >&2
    exit 1
}

usage() {
    echo -e "${CYAN}Spectra Test Runner${NC}"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  unit          Run unit tests (default)"
    echo "  integration   Run integration tests (starts required services)"
    echo "  all           Run unit + integration"
    echo "  coverage      Run unit tests with the CI coverage gate"
    echo "  load          Run load/rate-limit tests via the Docker test stack"
    echo "  performance   Run performance smoke tests via the Docker test stack"
    echo "  soak          Run soak/stability tests via the Docker test stack"
    echo "  live-smoke    Run live API/UI/LLM smoke tests against APP_BASE_URL"
    echo "  file <path>   Run a specific test file (unit runner)"
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help"
    echo ""
    echo "Environment:"
    echo "  REBUILD=1     Force rebuild the Docker test image"
}

compose() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

build_runner() {
    if [[ "${REBUILD:-0}" == "1" ]]; then
        compose --profile test build unit-test-runner
    fi
}

run_unit_runner() {
    # unit-test-runner only depends on db (compose pulls it up automatically).
    build_runner
    compose --profile test run --rm unit-test-runner "$*"
}

run_stack_harness() {
    local mode="${1}"
    shift || true

    "$PROJECT_ROOT/tests/run_load_tests.sh" "${mode}" "$@"
}

collect_compose_logs() {
    local out_dir="/tmp/spectra-live-smoke"
    if [[ "${SPECTRA_KEEP_TEST_ARTIFACTS:-0}" == "1" ]]; then
        out_dir="$PROJECT_ROOT/reports/live-smoke"
    fi
    mkdir -p "$out_dir"
    compose --profile app --profile test ps > "$out_dir/compose-ps.txt" 2>&1 || true
    compose --profile app --profile test logs --no-color --tail=300 \
        > "$out_dir/compose-logs.txt" 2>&1 || true
    echo -e "${YELLOW}Compose diagnostics written to ${out_dir}${NC}"
}

bootstrap_test_garage() {
    echo -e "${CYAN}Bootstrapping Garage buckets for live smoke...${NC}"
    GARAGE_CONTAINER="$(compose ps -q garage)" \
    GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}" \
    GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}" \
    GARAGE_PRINT_CREDENTIALS=0 \
        "$PROJECT_ROOT/deploy/docker/garage-init.sh"
}

run_live_smoke() {
    if [[ "${START_STACK:-0}" == "1" ]]; then
        echo -e "${CYAN}Starting test stack for live smoke...${NC}"
        docker compose --env-file "$PROJECT_ROOT/.env.test" -f "$COMPOSE_FILE" --profile app --profile test up -d
        export APP_BASE_URL="${APP_BASE_URL:-http://localhost:15080}"
        bootstrap_test_garage
    fi

    trap 'collect_compose_logs' ERR
    python3 "$PROJECT_ROOT/scripts/live_smoke.py"
    trap - ERR
}

ensure_env_test
CMD="${1:-unit}"

case "$CMD" in
    unit)
        run_unit_runner "python -m pytest tests/unit/ -q --override-ini=addopts="
        ;;
    integration)
        echo -e "${CYAN}Running integration tests via Compose (profiles app + test)...${NC}"
        compose --profile app --profile test run --rm test-runner \
            "python -m pytest tests/integration/ -q --override-ini=addopts= -x -k 'not live and not e2e'"
        ;;
    all)
        run_unit_runner "python -m pytest tests/unit/ -q --override-ini=addopts="
        compose --profile app --profile test run --rm test-runner \
            "python -m pytest tests/integration/ -q --override-ini=addopts= -k 'not live and not e2e'"
        ;;
    coverage)
        run_unit_runner "python -m pytest tests/unit/ -q --override-ini=addopts= --cov=spectra_api --cov=spectra_worker --cov=spectra_ai --cov=spectra_scheduler --cov=spectra_ai_core --cov=spectra_billing --cov=spectra_common --cov=spectra_mission --cov=spectra_persistence --cov=spectra_scaling --cov=spectra_storage_policy --cov=spectra_tools_core --cov-report=term-missing --cov-fail-under=67"
        ;;
    load)
        run_stack_harness load "${@:2}"
        ;;
    performance)
        run_stack_harness performance "${@:2}"
        ;;
    soak)
        run_stack_harness soak "${@:2}"
        ;;
    live-smoke)
        run_live_smoke
        ;;
    file)
        if [[ -z "${2:-}" ]]; then
            echo -e "${RED}Error: specify a test file path${NC}"
            echo "Usage: $0 file tests/unit/test_foo.py"
            exit 1
        fi
        run_unit_runner "python -m pytest $2 -v --override-ini=addopts="
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        echo -e "${RED}Unknown command: $CMD${NC}"
        usage
        exit 1
        ;;
esac
