#!/usr/bin/env bash
# Print suggested AUTOSCALE_* and worker scale hints from CPU + RAM (Linux hosts).
# Does not modify anything — paste into .env if useful.
#
# Usage:
#   ./scripts/ops/suggest-compose-scale.sh
#
set -euo pipefail

cpus="$(nproc 2>/dev/null || echo 4)"
mem_kb=""
if [[ -r /proc/meminfo ]]; then
  mem_kb="$(awk '/MemTotal:/ {print $2}' /proc/meminfo)"
fi
mem_gb=8
if [[ -n "$mem_kb" ]]; then
  mem_gb=$((mem_kb / 1024 / 1024))
fi

# Heuristic: reserve ~2 GB for OS + Docker metadata; ~1.5 GB per worker is a floor guess (tune per image).
usable=$((mem_gb - 2))
[[ "$usable" -lt 1 ]] && usable=1
worker_max=$((usable * 2 / 3))
[[ "$worker_max" -lt 1 ]] && worker_max=1
[[ "$worker_max" -gt "$cpus" ]] && worker_max="$cpus"

api_max=$((cpus / 2))
[[ "$api_max" -lt 1 ]] && api_max=1
[[ "$api_max" -gt 4 ]] && api_max=4

ai_max=$((cpus / 3))
[[ "$ai_max" -lt 1 ]] && ai_max=1
[[ "$ai_max" -gt 3 ]] && ai_max=3

cat <<EOF
# Detected: cpus=${cpus} mem_guess=${mem_gb}GiB (from /proc/meminfo if available)
AUTOSCALE_WORKER_MAX=${worker_max}
AUTOSCALE_API_MAX=${api_max}
AUTOSCALE_AI_MAX=${ai_max}
# Optional: docker compose --scale worker=N  (start with ${worker_max})
EOF
