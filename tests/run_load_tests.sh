#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
COMPOSE_FILE="${PROJECT_DIR}/docker/docker-compose.test.yml"
KEEP_STACK="${KEEP_STACK:-0}"
export GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}"
export GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}"

usage() {
    echo "Usage: ${0} [load|performance|soak|all] [-- <extra pytest args>]"
    echo ""
    echo "Examples:"
    echo "  ${0} load"
    echo "  ${0} performance -- -k auth_me"
    echo "  ${0} soak -- -k mixed"
    echo "  KEEP_STACK=1 ${0} all"
}

wait_for_service_health() {
    local service_name="${1}"
    local max_attempts="${2}"
    local container_id=""
    local status=""
    local attempt="0"

    container_id="$(docker compose -f "${COMPOSE_FILE}" ps -q "${service_name}")"
    if [[ -z "${container_id}" ]]; then
        echo "ERROR: could not resolve container id for ${service_name}" >&2
        return 1
    fi

    for (( attempt=1; attempt<=max_attempts; attempt++ )); do
        status="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}" 2>/dev/null || true)"
        if [[ "${status}" == "healthy" ]]; then
            echo "${service_name} is healthy"
            return 0
        fi
        sleep 2
    done

    echo "ERROR: ${service_name} did not become healthy" >&2
    docker compose -f "${COMPOSE_FILE}" logs --tail=60 "${service_name}" >&2 || true
    return 1
}

cleanup() {
    if [[ "${KEEP_STACK}" == "1" ]]; then
        echo "Keeping Docker test stack running (KEEP_STACK=1)"
        return
    fi

    docker compose -f "${COMPOSE_FILE}" down -v --remove-orphans >/dev/null 2>&1 || true
}

bootstrap_garage() {
    local garage_container=""

    garage_container="$(docker compose -f "${COMPOSE_FILE}" ps -q garage)"
    if [[ -z "${garage_container}" ]]; then
        echo "ERROR: could not resolve Garage container id" >&2
        return 1
    fi

    GARAGE_CONTAINER="${garage_container}" \
    GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY}" \
    GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY}" \
    bash "${PROJECT_DIR}/docker/garage-init.sh"
}

MODE="${1:-all}"
if [[ "${MODE}" == "-h" || "${MODE}" == "--help" ]]; then
    usage
    exit 0
fi

shift || true
if [[ "${1:-}" == "--" ]]; then
    shift
fi
EXTRA_PYTEST_ARGS=("$@")

case "${MODE}" in
    load)
        MARK_EXPR="load"
        TEST_TARGETS=(tests/load)
        ;;
    performance)
        MARK_EXPR="performance"
        TEST_TARGETS=(tests/performance tests/integration/test_queue.py)
        ;;
    soak)
        MARK_EXPR="soak"
        TEST_TARGETS=(tests/soak)
        ;;
    all)
        MARK_EXPR="load or performance or soak"
        TEST_TARGETS=(tests/load tests/performance tests/soak tests/integration/test_queue.py)
        ;;
    *)
        echo "ERROR: unknown mode '${MODE}'" >&2
        usage
        exit 1
        ;;
esac

trap cleanup EXIT

echo "Starting the Docker test stack for ${MODE} validation"
docker compose -f "${COMPOSE_FILE}" up -d --build db garage redis >/dev/null

bootstrap_garage

docker compose -f "${COMPOSE_FILE}" up -d --build app app-replica caddy tools >/dev/null

wait_for_service_health app 60
wait_for_service_health app-replica 60
wait_for_service_health caddy 60
wait_for_service_health tools 60

export LOAD_TEST_APP_URL="${LOAD_TEST_APP_URL:-http://127.0.0.1:15000}"
export LOAD_TEST_APP_REPLICA_URL="${LOAD_TEST_APP_REPLICA_URL:-http://127.0.0.1:15001}"
export LOAD_TEST_CADDY_URL="${LOAD_TEST_CADDY_URL:-http://127.0.0.1:15080}"
export LOAD_TEST_RESET_RATE_LIMIT_STATE="${LOAD_TEST_RESET_RATE_LIMIT_STATE:-1}"

printf -v PYTEST_CMD '%q ' \
    python3 -m pytest \
    "${TEST_TARGETS[@]}" \
    -m "${MARK_EXPR}" \
    -q \
    --override-ini=addopts= \
    "${EXTRA_PYTEST_ARGS[@]}"

echo "Running ${MODE} tests through the dedicated runner service"
docker compose -f "${COMPOSE_FILE}" run --rm --no-deps --entrypoint sh load-test-runner -c \
    "pip install -q pytest pytest-asyncio pytest-dotenv httpx redis websockets && ${PYTEST_CMD}"