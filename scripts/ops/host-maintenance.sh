#!/usr/bin/env bash
# Host-level maintenance for Spectra workers / single-node VPS (not compose-specific).
# Safe to run from cron weekly. Set AGGRESSIVE=1 for stronger managed-image prune
# (images unused 72h+). Volumes and other Docker projects are never touched.
# Build-cache pruning is global in Docker; set PRUNE_BUILDER_CACHE=1 only on a
# host dedicated to Spectra if reclaiming unrelated build caches is acceptable.
#
# Usage:
#   sudo ./scripts/ops/host-maintenance.sh
#   AGGRESSIVE=1 sudo ./scripts/ops/host-maintenance.sh
#
set -euo pipefail

if [[ "${EUID:-}" != "0" ]]; then
  echo "[host-maintenance] re-run as root for journald vacuum" >&2
fi

if command -v journalctl >/dev/null 2>&1; then
  journalctl --vacuum-time="${JOURNAL_VACUUM_TIME:-14d}" 2>/dev/null || true
fi

if command -v logrotate >/dev/null 2>&1 && [[ -f /etc/logrotate.conf ]]; then
  logrotate /etc/logrotate.conf 2>/dev/null || true
fi

if command -v docker >/dev/null 2>&1; then
  if [[ "${PRUNE_BUILDER_CACHE:-0}" == "1" ]]; then
    docker builder prune -f --filter "until=${BUILD_CACHE_UNTIL:-240h}" 2>/dev/null || true
  fi
  docker container prune -f --filter "label=spectra.managed=true" --filter "until=${CONTAINER_PRUNE_UNTIL:-168h}" 2>/dev/null || true
  if [[ "${AGGRESSIVE:-0}" == "1" ]]; then
    docker image prune -af --filter "label=spectra.managed=true" --filter "until=72h" 2>/dev/null || true
  else
    docker image prune -f --filter "label=spectra.managed=true" --filter "until=168h" 2>/dev/null || true
  fi
fi

echo "[host-maintenance] done"
