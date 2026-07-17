#!/usr/bin/env bash
# Full platform verification (Docker): merges CI parity, load/perf/soak harness,
# Playwright UI suite, and live target scans. Optionally runs the full LLM live
# slice when LLM_API_KEY or OPENAI_API_KEY is set in .env.test.
#
# Usage (repository root):
#   ./scripts/runbooks/full-test-matrix.sh
#
# Environment (all optional):
#   ENCRYPTION_KEY           Same as CI (default: test-encryption-key)
#   SKIP_CI_PARITY=1       Skip static + unit + settings + integration (ci-parity all)
#   SKIP_LOAD_HARNESS=1    Skip tests/run_load_tests.sh all
#   SKIP_UI_E2E=1          Skip tests/run_ui_tests.sh (Playwright)
#   SKIP_LIVE_TARGETS=1    Skip tests/run_live_tests.sh --targets
#   SKIP_LIVE_FULL=1       Never run full LLM live suite (even if keys present)
#   SKIP_API_E2E=1         Skip async HTTP e2e (test_api_live.py; starts app stack if needed)
#   RUN_LIVE_SMOKE=1       After matrix, START_STACK=1 scripts/test.sh live-smoke (multi-minute)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-spectra-full-matrix}"
cd "$ROOT"

ensure_env_test() {
  if [[ -f .env.test ]]; then
    return 0
  fi
  if [[ -f .env.test.example ]]; then
    cp .env.test.example .env.test
    echo "[full-test-matrix] created .env.test from .env.test.example"
    return 0
  fi
  echo "[full-test-matrix] ERROR: missing .env.test and no .env.test.example" >&2
  exit 1
}

export ENCRYPTION_KEY="${ENCRYPTION_KEY:-test-encryption-key}"

ensure_env_test

run_ci_parity() {
  echo ">>> [full-test-matrix] ci-parity.sh all"
  COMPOSE_DOWN=1 ./scripts/runbooks/ci-parity.sh all
}

run_load() {
  echo ">>> [full-test-matrix] run_load_tests.sh all"
  ./tests/run_load_tests.sh all
}

run_ui() {
  echo ">>> [full-test-matrix] run_ui_tests.sh (Playwright)"
  ./tests/run_ui_tests.sh
}

run_live_targets() {
  echo ">>> [full-test-matrix] run_live_tests.sh --targets"
  ./tests/run_live_tests.sh --targets
}

run_live_full_maybe() {
  # shellcheck disable=SC1091
  source .env.test
  if [[ -z "${LLM_API_KEY:-}" ]] && [[ -n "${OPENAI_API_KEY:-}" ]]; then
    export LLM_API_KEY="$OPENAI_API_KEY"
  fi
  if [[ "${SKIP_LIVE_FULL:-0}" == "1" ]]; then
    echo ">>> [full-test-matrix] SKIP full live suite (SKIP_LIVE_FULL=1)"
    return 0
  fi
  if [[ -z "${LLM_API_KEY:-}" || "${LLM_API_KEY}" == "your-api-key-here" ]]; then
    echo ">>> [full-test-matrix] SKIP full live LLM suite (set LLM_API_KEY or OPENAI_API_KEY in .env.test)"
    return 0
  fi
  echo ">>> [full-test-matrix] run_live_tests.sh (full — LLM + targets + ops smoke)"
  ./tests/run_live_tests.sh
}

run_api_e2e() {
  if [[ "${SKIP_API_E2E:-0}" == "1" ]]; then
    echo ">>> [full-test-matrix] SKIP API async e2e (SKIP_API_E2E=1)"
    return 0
  fi
  echo ">>> [full-test-matrix] Async API e2e (tests/e2e/test_api_live.py)"
  export ENV_FILE="${ROOT}/.env.test"
  COMPOSE=(docker compose -f "${ROOT}/deploy/docker/compose.yaml")
  echo ">>> [full-test-matrix] compose --profile app up (stack for API e2e)"
  ENV_FILE="${ENV_FILE}" "${COMPOSE[@]}" --profile app up -d --build

  GARAGE_CONTAINER="$("${COMPOSE[@]}" ps -q garage)"
  export GARAGE_CONTAINER
  GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}" \
    GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}" \
    GARAGE_PRINT_CREDENTIALS=0 \
    bash "${ROOT}/deploy/docker/garage-init.sh"

  echo ">>> [full-test-matrix] waiting for app health on :5000"
  _ready=""
  for _i in $(seq 1 120); do
    if curl -sf http://127.0.0.1:5000/api/health >/dev/null 2>&1; then
      _ready=1
      break
    fi
    sleep 2
  done
  if [[ -z "${_ready}" ]]; then
    echo "[full-test-matrix] ERROR: app did not become healthy on :5000" >&2
    ENV_FILE="${ENV_FILE}" "${COMPOSE[@]}" --profile app logs --tail=80 app >&2 || true
    exit 1
  fi

  ENV_FILE="${ENV_FILE}" "${COMPOSE[@]}" --profile app --profile test run --rm --no-deps test-runner \
    "python3 -m pytest tests/e2e/test_api_live.py -v --tb=short --override-ini=addopts= -p no:cov"
}

if [[ "${SKIP_CI_PARITY:-0}" != "1" ]]; then
  run_ci_parity
fi

if [[ "${SKIP_LOAD_HARNESS:-0}" != "1" ]]; then
  run_load
fi

if [[ "${SKIP_UI_E2E:-0}" != "1" ]]; then
  run_ui
fi

if [[ "${SKIP_LIVE_TARGETS:-0}" != "1" ]]; then
  run_live_targets
fi

run_live_full_maybe

run_api_e2e

if [[ "${RUN_LIVE_SMOKE:-0}" == "1" ]]; then
  echo ">>> optional live_smoke.py (requires reachable APP_BASE_URL)"
  START_STACK=1 APP_BASE_URL="${APP_BASE_URL:-http://localhost:15080}" ./scripts/test.sh live-smoke
fi

echo ">>> full-test-matrix.sh: OK"
