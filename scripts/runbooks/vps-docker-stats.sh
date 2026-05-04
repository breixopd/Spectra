#!/usr/bin/env bash
# One-shot Docker resource snapshot on a VPS (for profiling / capacity planning).
#
# Usage:
#   VPS=root@your.host ./scripts/runbooks/vps-docker-stats.sh
#
set -euo pipefail

REMOTE="${VPS:?Set VPS=ssh-target}"
REMOTE_DIR="${VPS_REMOTE_DIR:-/root/spectra}"

exec ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$REMOTE" \
  "echo '=== docker stats (no-stream) ===' && docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' 2>/dev/null | head -50; \
   echo; echo '=== compose project (if ${REMOTE_DIR}) ==='; \
   cd '${REMOTE_DIR}' 2>/dev/null && docker compose -f docker/compose.yaml ps 2>/dev/null || true; \
   echo; echo '=== disk ==='; df -h / /var/lib/docker 2>/dev/null | tail -n +1"
