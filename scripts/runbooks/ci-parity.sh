#!/usr/bin/env bash
# Local / VPS gate: mirror GitHub Actions CI test + static-analysis (Docker only).
#
# Usage (from repository root):
#   ./scripts/runbooks/ci-parity.sh           # same as: ci-parity.sh ci
#   ./scripts/runbooks/ci-parity.sh ci       # static analysis + unit(cov>=70%) + settings
#   ./scripts/runbooks/ci-parity.sh all      # ci + integration (Garage + test-runner)
#   ./scripts/runbooks/ci-parity.sh static|lint|type|unit|settings|integration
#
# Environment:
#   ENCRYPTION_KEY=test-encryption-key   # default matches CI
#   SPECTRA_CI_IMAGE=spectra-test-ci     # image tag (matches CI Dockerfile.test)
#   SKIP_PYRIGHT=1                       # skip pyright (faster local iteration)
#   SKIP_BANDIT=1                        # skip bandit
#   COMPOSE_DOWN=1                       # after `all`, run compose down for app+test+targets
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

export ENCRYPTION_KEY="${ENCRYPTION_KEY:-test-encryption-key}"
IMAGE="${SPECTRA_CI_IMAGE:-spectra-test-ci}"
COMPOSE=(docker compose -f docker/compose.yaml)

ensure_env_test() {
  if [[ -f .env.test ]]; then
    return 0
  fi
  if [[ -f .env.test.example ]]; then
    cp .env.test.example .env.test
    echo "[ci-parity] Created .env.test from .env.test.example"
    return 0
  fi
  echo "[ci-parity] ERROR: missing .env.test and no .env.test.example to copy." >&2
  exit 1
}

build_ci_image() {
  echo "==> Build Docker test image ($IMAGE) from docker/Dockerfile.test"
  docker build -f docker/Dockerfile.test -t "$IMAGE" .
}

lint_ruff_and_boundaries() {
  echo "==> Ruff"
  docker run --rm "$IMAGE" python -m ruff check spectra_platform/ tests/ services/ packages/
  echo "==> Import boundaries"
  docker run --rm "$IMAGE" python scripts/check_import_boundaries.py
}

typecheck_job() {
  if [[ "${SKIP_PYRIGHT:-0}" == "1" ]]; then
    echo "==> SKIP pyright (SKIP_PYRIGHT=1)"
    return 0
  fi
  echo "==> Pyright"
  docker run --rm "$IMAGE" sh -c "pip install --no-cache-dir pyright >/dev/null && pyright"
}

bandit_job() {
  if [[ "${SKIP_BANDIT:-0}" == "1" ]]; then
    echo "==> SKIP bandit (SKIP_BANDIT=1)"
    return 0
  fi
  echo "==> Bandit"
  docker run --rm "$IMAGE" bandit -r spectra_platform/ -c pyproject.toml --severity-level high --confidence-level high
}

static_analysis_job() {
  build_ci_image
  lint_ruff_and_boundaries
  typecheck_job
  bandit_job
}

tensorzero_check_job() {
  echo "==> TensorZero TOML parse"
  "${COMPOSE[@]}" --profile test run --rm --no-deps unit-test-runner \
    "python -c \"import tomllib; tomllib.load(open('config/tensorzero.toml', 'rb')); print('tensorzero.toml: OK')\""
}

unit_coverage_job() {
  echo "==> Build unit-test-runner"
  "${COMPOSE[@]}" --profile test build unit-test-runner
  tensorzero_check_job
  echo "==> Unit tests + coverage (fail-under 70%, matches CI)"
  set +e
  "${COMPOSE[@]}" --profile test run --name spectra-unit-local unit-test-runner \
    "python -m pytest tests/unit/ -q --override-ini=addopts= --cov=spectra_platform --cov=spectra_api --cov=spectra_worker --cov=spectra_ai --cov=spectra_scheduler --cov-report=term-missing --cov-report=xml:/tmp/coverage.xml --cov-fail-under=70"
  st=$?
  docker rm -f spectra-unit-local >/dev/null 2>&1 || true
  set -e
  if [[ "$st" -ne 0 ]]; then
    echo "[ci-parity] Unit/coverage failed (exit $st)" >&2
    exit "$st"
  fi
}

settings_job() {
  echo "==> Settings test-runner (matches CI)"
  "${COMPOSE[@]}" --profile test run --rm settings-test-runner
}

integration_job() {
  echo "==> Build test-runner + start Garage (matches CI integration-test job)"
  "${COMPOSE[@]}" --profile app --profile test build test-runner
  ENV_FILE=../.env.test "${COMPOSE[@]}" --profile app --profile test up -d garage
  GARAGE_CONTAINER="$("${COMPOSE[@]}" ps -q garage)" \
    GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}" \
    GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}" \
    GARAGE_PRINT_CREDENTIALS=0 \
    bash docker/garage-init.sh
  echo "==> Integration pytest (excludes live / e2e)"
  "${COMPOSE[@]}" --profile app --profile test run --rm test-runner \
    "python -m pytest tests/integration/ -v --tb=short --timeout=120 --override-ini=addopts= -k 'not live and not e2e'"
}

compose_down_optional() {
  if [[ "${COMPOSE_DOWN:-0}" == "1" ]]; then
    echo "==> COMPOSE_DOWN=1: tearing down app+test+targets stack"
    ENV_FILE=../.env.test "${COMPOSE[@]}" --profile app --profile test --profile targets down -v --remove-orphans || true
  fi
}

MODE="${1:-ci}"
ensure_env_test

case "$MODE" in
  static)
    static_analysis_job
    ;;
  lint)
    build_ci_image
    lint_ruff_and_boundaries
    ;;
  type)
    build_ci_image
    typecheck_job
    ;;
  unit)
    unit_coverage_job
    ;;
  settings)
    settings_job
    ;;
  integration)
    integration_job
    compose_down_optional
    ;;
  ci)
    static_analysis_job
    unit_coverage_job
    settings_job
    ;;
  all)
    static_analysis_job
    unit_coverage_job
    settings_job
    integration_job
    compose_down_optional
    ;;
  -h|--help)
    sed -n '1,22p' "$0"
    exit 0
    ;;
  *)
    echo "Unknown mode: $MODE (use: static, lint, type, unit, settings, integration, ci, all)" >&2
    exit 1
    ;;
esac

echo "==> ci-parity ($MODE): OK"
