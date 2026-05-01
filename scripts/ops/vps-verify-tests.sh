#!/usr/bin/env bash
# Run the same unit + coverage gate as CI on a VPS or staging host (Docker).
# Usage:
#   ./scripts/ops/vps-verify-tests.sh              # from repo root
#   ./scripts/ops/vps-verify-tests.sh /path/to/Spectra
#
# Prerequisites: Docker, docker compose plugin, repo at requested path with
# docker/compose.yaml and .env.test (copied from .env.test.example if missing).
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

if [[ ! -f docker/compose.yaml ]]; then
  echo "error: docker/compose.yaml not found under $ROOT" >&2
  exit 1
fi

if [[ ! -f .env.test ]]; then
  if [[ -f .env.test.example ]]; then
    cp .env.test.example .env.test
    echo "warn: created .env.test from .env.test.example" >&2
  else
    echo "error: .env.test missing and no .env.test.example" >&2
    exit 1
  fi
fi

COMPOSE=(docker compose -f docker/compose.yaml --profile test)

"${COMPOSE[@]}" build unit-test-runner
"${COMPOSE[@]}" run --rm unit-test-runner \
  "python -m pytest tests/unit/ -q --override-ini=addopts= \
  --cov=app --cov=spectra_api --cov=spectra_worker --cov=spectra_ai --cov=spectra_scheduler \
  --cov-fail-under=70"
