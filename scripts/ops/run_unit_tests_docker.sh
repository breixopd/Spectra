#!/usr/bin/env bash
# Thin wrapper — canonical CI-parity unit gate (coverage ≥67%, TensorZero parse).
# Usage (repository root): ./scripts/ops/run_unit_tests_docker.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/runbooks/ci-parity.sh" unit
