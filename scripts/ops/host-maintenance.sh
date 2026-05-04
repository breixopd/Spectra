#!/usr/bin/env bash
# Host-level maintenance for Spectra workers / single-node VPS (not compose-specific).
# Safe to run from cron weekly. Set AGGRESSIVE=1 for stronger Docker prune (images unused 72h+).
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

if [[ -d /var/log ]]; then
  find /var/log -type f -name "*.gz" -mtime +"${OLD_LOG_DAYS:-30}" -delete 2>/dev/null || true
fi

if command -v docker >/dev/null 2>&1; then
  docker builder prune -f --filter "until=${BUILD_CACHE_UNTIL:-240h}" 2>/dev/null || true
  if [[ "${AGGRESSIVE:-0}" == "1" ]]; then
    docker image prune -af --filter "until=72h" 2>/dev/null || true
  else
    docker image prune -f --filter "until=168h" 2>/dev/null || true
  fi
fi

echo "[host-maintenance] done"
