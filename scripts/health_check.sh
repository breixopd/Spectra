#!/bin/bash
# Spectra Health Check Script
# Reusable health check with retries and exponential backoff.
#
# Usage: ./scripts/health_check.sh <url> [max_retries] [initial_wait_secs]
# Returns: 0 on success, 1 on failure
#
# Examples:
#   ./scripts/health_check.sh 'http://localhost:5000/api/v1/health?scope=public'
#   ./scripts/health_check.sh 'http://localhost:5000/api/health/ready' 5 2

set -euo pipefail

URL="${1:-}"
MAX_RETRIES="${2:-5}"
INITIAL_WAIT="${3:-2}"

usage() {
    cat <<EOF
Usage: $(basename "$0") <url> [max_retries] [initial_wait_secs]

Arguments:
  url               Health check endpoint URL (required)
  max_retries       Maximum retry attempts (default: 5)
  initial_wait_secs Initial wait before first retry in seconds (default: 2)

Retries use exponential backoff: wait = initial_wait * 2^attempt

Exit codes:
  0  Health check passed
  1  Health check failed after all retries
EOF
    exit 1
}

if [ -z "$URL" ]; then
    usage
fi

# ── Primary health check (required) ─────────────────────────────

FAILED=0

for i in $(seq 0 "$MAX_RETRIES"); do
    if curl -sfL --max-time 10 "$URL" > /dev/null 2>&1; then
        echo "Health check passed: $URL (attempt $((i + 1)))"
        break
    fi

    if [ "$i" -lt "$MAX_RETRIES" ]; then
        WAIT=$(( INITIAL_WAIT * (2 ** i) ))
        echo "Health check failed (attempt $((i + 1))/$((MAX_RETRIES + 1))), retrying in ${WAIT}s..."
        sleep "$WAIT"
    else
        echo "Health check FAILED after $((MAX_RETRIES + 1)) attempts: $URL"
        FAILED=1
    fi
done

# ── Supplementary checks (best-effort) ──────────────────────────

# Derive base URL from the primary URL (strip path)
BASE_URL=$(echo "$URL" | sed -E 's|/api(/v1)?/health.*||')

# Canonical public health endpoint — verifies public API routes work
if curl -sfL --max-time 10 "${BASE_URL}/api/v1/health?scope=public" > /dev/null 2>&1; then
    echo "Supplementary check passed: canonical public health"
else
    echo "WARN: /api/v1/health?scope=public did not respond (non-critical)"
fi

REDIS_URL="${REDIS_URL:-redis://localhost:6379}"

# Redis: check if reachable via docker container
if docker ps -q -f "name=spectra-redis" 2>/dev/null | grep -q .; then
    if docker exec spectra-redis redis-cli ping 2>/dev/null | grep -q PONG; then
        echo "Supplementary check passed: Redis (PONG)"
    else
        echo "WARN: Redis container exists but is not responding"
    fi
fi

# Database: check via docker container
if docker ps -q -f "name=spectra-db" 2>/dev/null | grep -q .; then
    if docker exec spectra-db pg_isready -U spectra -d spectra > /dev/null 2>&1; then
        echo "Supplementary check passed: PostgreSQL (pg_isready)"
    else
        echo "WARN: PostgreSQL container exists but is not ready"
    fi
fi

# ── Deep checks (opt-in) ─────────────────────────────────────────

if [ "${HEALTH_CHECK_FULL:-0}" = "1" ]; then
    echo "Running full deep health checks..."
    AUTH_HEADER=()
    if [ -n "${SERVICE_AUTH_SECRET:-}" ]; then
        AUTH_HEADER=(-H "X-Service-Auth: ${SERVICE_AUTH_SECRET}")
    fi

    if curl -sf --max-time 20 "${AUTH_HEADER[@]}" "${BASE_URL}/api/v1/health?detail=full&include=services,nodes" > /dev/null 2>&1; then
        echo "Deep check passed: canonical full platform health"
    else
        echo "WARN: canonical full platform health did not respond or was degraded"
    fi

    # AI service direct check (if AI_SERVICE_URL is set)
    if [ -n "${AI_SERVICE_URL:-}" ]; then
        if curl -sf --max-time 10 "${AI_SERVICE_URL}/health" > /dev/null 2>&1; then
            echo "Deep check passed: AI service (${AI_SERVICE_URL})"
        else
            echo "WARN: AI service not responding at ${AI_SERVICE_URL}"
        fi
    fi

    echo "Deep check note: service, storage, and node details are covered by canonical full health"
fi

exit $FAILED
