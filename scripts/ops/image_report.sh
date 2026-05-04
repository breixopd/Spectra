#!/usr/bin/env bash
# Report first-party image sizes and largest layers.
set -euo pipefail

IMAGES=(
  "${REGISTRY:-}spectra-app:${VERSION:-dev}"
  "${REGISTRY:-}spectra-ai-svc:${VERSION:-dev}"
  "${REGISTRY:-}spectra-scheduler:${VERSION:-dev}"
  "${REGISTRY:-}spectra-worker:${VERSION:-dev}"
  "${REGISTRY:-}spectra-caddy:${VERSION:-dev}"
)

printf '%-34s %12s\n' "IMAGE" "SIZE"
for image in "${IMAGES[@]}"; do
  if docker image inspect "${image}" >/dev/null 2>&1; then
    size_bytes="$(docker image inspect "${image}" --format '{{.Size}}')"
    size_mb="$(awk "BEGIN {printf \"%.1f MB\", ${size_bytes}/1024/1024}")"
    printf '%-34s %12s\n' "${image}" "${size_mb}"
  else
    printf '%-34s %12s\n' "${image}" "missing"
  fi
done

echo
echo "Largest layers:"
for image in "${IMAGES[@]}"; do
  if docker image inspect "${image}" >/dev/null 2>&1; then
    echo
    echo "## ${image}"
    docker history --no-trunc --format '{{.Size}}\t{{.CreatedBy}}' "${image}" \
      | awk -F '\t' '
        function bytes(size, value, unit) {
          value = size
          unit = size
          sub(/[[:alpha:]]+.*/, "", value)
          sub(/^[0-9.]+/, "", unit)
          if (unit == "GB") return value * 1024 * 1024 * 1024
          if (unit == "MB") return value * 1024 * 1024
          if (unit == "kB" || unit == "KB") return value * 1024
          if (unit == "B") return value
          return 0
        }
        { print bytes($1) "\t" $0 }
      ' \
      | sort -nr \
      | cut -f2- \
      | sed -n '1,8p'
  fi
done

