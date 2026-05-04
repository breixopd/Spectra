#!/usr/bin/env bash
# Run the full Docker test matrix on a VPS (same entrypoint as local `./scripts/runbooks/full-test-matrix.sh`).
#
# Prerequisites:
#   - SSH key loaded (BatchMode); VPS has Docker and repo checkout at VPS_REMOTE_DIR
#   - Remote `.env.test` already present (rsync excludes it — see vps-sync.sh)
#
# Usage:
#   VPS=root@your.host ./scripts/runbooks/vps-full-test-matrix.sh
#   VPS_RSYNC=0 VPS=root@host ./scripts/runbooks/vps-full-test-matrix.sh   # skip rsync
#   VPS_BACKGROUND=1 VPS=root@host ./scripts/runbooks/vps-full-test-matrix.sh  # nohup on server
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE="${VPS:?Set VPS=ssh-target (e.g. root@203.0.113.10)}"
REMOTE_DIR="${VPS_REMOTE_DIR:-/root/spectra}"
RSYNC="${VPS_RSYNC:-1}"
LOG="${VPS_MATRIX_LOG:-/tmp/spectra-matrix-vps.log}"

if [[ "$RSYNC" == "1" ]]; then
  VPS="$REMOTE" "${ROOT}/scripts/runbooks/vps-sync.sh"
fi

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$REMOTE")

if [[ "${VPS_BACKGROUND:-0}" == "1" ]]; then
  "${SSH[@]}" "cd '${REMOTE_DIR}' && chmod +x scripts/runbooks/full-test-matrix.sh 2>/dev/null || true && \
    nohup env COMPOSE_PROFILES=app,test ./scripts/runbooks/full-test-matrix.sh >'${LOG}' 2>&1 & echo \"[vps-full-test-matrix] started PID \$! log ${LOG}\""
  echo "[vps-full-test-matrix] tail with:  VPS=$REMOTE ssh ... 'tail -f ${LOG}'"
  exit 0
fi

exec "${SSH[@]}" "cd '${REMOTE_DIR}' && exec env COMPOSE_PROFILES=app,test ./scripts/runbooks/full-test-matrix.sh"
