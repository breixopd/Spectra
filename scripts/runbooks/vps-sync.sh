#!/usr/bin/env bash
# Rsync Spectra to a VPS without overwriting remote secrets (excludes .env.test).
#
# Usage:
#   VPS=root@103.47.224.118 ./scripts/runbooks/vps-sync.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${VPS:?Set VPS=root@host}"
exec rsync -avz --delete \
  -e 'ssh -o StrictHostKeyChecking=accept-new' \
  --exclude '.env.test' \
  --exclude 'node_modules' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'htmlcov' \
  --exclude '.pytest_cache' \
  --exclude 'data/' \
  --exclude '*.pyc' \
  "${ROOT}/" "${REMOTE}:/root/spectra/"
