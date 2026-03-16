#!/usr/bin/env bash
# scripts/test.sh — Docker-based test runner for Spectra
#
# Usage:
#   ./scripts/test.sh              # Run unit tests (default)
#   ./scripts/test.sh unit         # Run unit tests
#   ./scripts/test.sh integration  # Run integration tests
#   ./scripts/test.sh all          # Run all tests
#   ./scripts/test.sh coverage     # Run with coverage report
#   ./scripts/test.sh file <path>  # Run a specific test file
#
# Environment:
#   SPECTRA_TEST_IMAGE  Override the Docker image (default: spectra-app)
#   REBUILD=1           Force rebuild the test image before running

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="${SPECTRA_TEST_IMAGE:-spectra-app}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    echo -e "${CYAN}Spectra Test Runner${NC}"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  unit          Run unit tests (default)"
    echo "  integration   Run integration tests (requires live services)"
    echo "  all           Run all tests"
    echo "  coverage      Run unit tests with coverage report"
    echo "  file <path>   Run a specific test file"
    echo "  compose       Run full test stack via docker-compose"
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help"
    echo ""
    echo "Environment:"
    echo "  REBUILD=1     Force rebuild the Docker image"
}

build_image() {
    if [[ "${REBUILD:-0}" == "1" ]] || ! docker image inspect "$IMAGE" &>/dev/null; then
        echo -e "${YELLOW}Building test image...${NC}"
        docker build -f "$PROJECT_ROOT/docker/Dockerfile.app" -t "$IMAGE" "$PROJECT_ROOT"
    fi
}

run_in_docker() {
    local pytest_args=("$@")
    build_image

    echo -e "${CYAN}Running: pytest ${pytest_args[*]}${NC}"

    docker run --rm \
        -e DATABASE_URL=sqlite+aiosqlite:///tmp/test.db \
        -e AI_PROVIDER=litellm \
        -e JWT_SECRET_KEY=test-secret-key \
        -e FULLY_AUTOMATED=true \
        -e PLUGIN_SAFE_MODE=false \
        -v "$PROJECT_ROOT/app:/app/app:ro" \
        -v "$PROJECT_ROOT/tests:/app/tests:ro" \
        -v "$PROJECT_ROOT/pytest.ini:/app/pytest.ini:ro" \
        -v "$PROJECT_ROOT/.env.test:/app/.env.test:ro" \
        -v "$PROJECT_ROOT/alembic:/app/alembic:ro" \
        -v "$PROJECT_ROOT/alembic.ini:/app/alembic.ini:ro" \
        -v "$PROJECT_ROOT/plugins:/app/plugins:ro" \
        -v "$PROJECT_ROOT/data:/app/data" \
        --entrypoint sh "$IMAGE" \
        -c "pip install -q pytest pytest-asyncio pytest-dotenv aiosqlite aiohttp httpx pytest-cov 2>/dev/null && python3 -m pytest ${pytest_args[*]}"
}

CMD="${1:-unit}"

case "$CMD" in
    unit)
        run_in_docker tests/unit/ -q --override-ini=addopts=
        ;;
    integration)
        echo -e "${YELLOW}Integration tests require live services (PostgreSQL, LLM, etc.)${NC}"
        echo -e "${YELLOW}Consider using: $0 compose${NC}"
        run_in_docker tests/integration/ -q --override-ini=addopts= -x
        ;;
    all)
        run_in_docker tests/ -q --override-ini=addopts= --ignore=tests/e2e
        ;;
    coverage)
        run_in_docker tests/unit/ \
            --override-ini=addopts= \
            --cov=app --cov-report=term-missing --cov-report=html:reports/coverage
        echo -e "${GREEN}Coverage report: reports/coverage/index.html${NC}"
        ;;
    file)
        if [[ -z "${2:-}" ]]; then
            echo -e "${RED}Error: specify a test file path${NC}"
            echo "Usage: $0 file tests/unit/test_foo.py"
            exit 1
        fi
        run_in_docker "$2" -v --override-ini=addopts=
        ;;
    compose)
        echo -e "${CYAN}Running full test stack via docker-compose...${NC}"
        docker compose -f "$PROJECT_ROOT/docker/docker-compose.test.yml" \
            run --rm test-runner
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
