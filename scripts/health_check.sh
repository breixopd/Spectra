#!/bin/bash
# Spectra Health Check Script
# Reusable health check with retries and exponential backoff.
#
# Usage: ./scripts/health_check.sh <url> [max_retries] [initial_wait_secs]
# Returns: 0 on success, 1 on failure
#
# Examples:
#   ./scripts/health_check.sh http://localhost:5000/api/health
#   ./scripts/health_check.sh http://localhost:5000/api/health 5 2

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

for i in $(seq 0 "$MAX_RETRIES"); do
    if curl -sf --max-time 10 "$URL" > /dev/null 2>&1; then
        echo "Health check passed: $URL (attempt $((i + 1)))"
        exit 0
    fi

    if [ "$i" -lt "$MAX_RETRIES" ]; then
        WAIT=$(( INITIAL_WAIT * (2 ** i) ))
        echo "Health check failed (attempt $((i + 1))/$((MAX_RETRIES + 1))), retrying in ${WAIT}s..."
        sleep "$WAIT"
    fi
done

echo "Health check FAILED after $((MAX_RETRIES + 1)) attempts: $URL"
exit 1
