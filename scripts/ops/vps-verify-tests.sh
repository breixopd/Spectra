#!/usr/bin/env bash
# VPS / staging: same unit + coverage gate as GitHub Actions `test` job.
# Delegates to scripts/runbooks/ci-parity.sh unit (single source of truth).
#
# Usage:
#   ./scripts/ops/vps-verify-tests.sh              # from repo root
#   ./scripts/ops/vps-verify-tests.sh /path/to/Spectra
set -euo pipefail

ROOT="$(cd "${1:-.}" && pwd)"
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

RUNBOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/../runbooks" && pwd)/ci-parity.sh"
exec "$RUNBOOK" unit
