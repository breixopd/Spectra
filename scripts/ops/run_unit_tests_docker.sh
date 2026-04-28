#!/usr/bin/env bash
# CI-parity unit tests (matches .github/workflows/ci.yml test job intent).
# Run on dev machine or VPS after `git pull`, from repository root:
#   ./scripts/ops/run_unit_tests_docker.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
docker compose -f docker/compose.yaml --profile test build unit-test-runner
exec docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python3 -m pytest tests/unit/ -q --no-cov --override-ini=addopts="
