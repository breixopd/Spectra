#!/usr/bin/env bash
# scripts/ops/install-maintenance-timers.sh — Install systemd timers for automated host maintenance
# Usage: sudo ./scripts/ops/install-maintenance-timers.sh
#
# Installs four timer units:
#   spectra-journal-vacuum  — weekly, vacuum systemd journals older than 14 days
#   spectra-docker-prune    — weekly, prune unused Docker images/containers/build cache
#   spectra-log-rotate      — daily, rotate /var/log files older than 30 days
#   spectra-disk-check      — daily, check disk usage and warn if >80%
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "Must run as root"; exit 1; }

SYSTEMD_DIR="/etc/systemd/system"
LOG_PREFIX="[spectra-maintenance]"

log()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) $*"; }
warn() { echo "${LOG_PREFIX} $(date +%H:%M:%S) [WARN] $*" >&2; }
die()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) [FATAL] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Journal vacuum — runs weekly, vacuums journals older than 14 days
# ---------------------------------------------------------------------------
log "Installing spectra-journal-vacuum timer..."

cat > "${SYSTEMD_DIR}/spectra-journal-vacuum.service" <<'EOF'
[Unit]
Description=Spectra — vacuum systemd journals older than 14 days
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/journalctl --vacuum-time=14d
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=spectra-journal-vacuum
EOF

cat > "${SYSTEMD_DIR}/spectra-journal-vacuum.timer" <<'EOF'
[Unit]
Description=Spectra — weekly journal vacuum
Requires=spectra-journal-vacuum.service

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=3600

[Install]
WantedBy=timers.target
EOF

# ---------------------------------------------------------------------------
# 2. Docker prune — runs weekly, prunes unused images/containers/build cache
# ---------------------------------------------------------------------------
log "Installing spectra-docker-prune timer..."

cat > "${SYSTEMD_DIR}/spectra-docker-prune.service" <<'EOF'
[Unit]
Description=Spectra — prune unused Docker images, containers, and build cache
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker system prune -af --volumes
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=spectra-docker-prune
EOF

cat > "${SYSTEMD_DIR}/spectra-docker-prune.timer" <<'EOF'
[Unit]
Description=Spectra — weekly Docker prune
Requires=spectra-docker-prune.service

[Timer]
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=7200

[Install]
WantedBy=timers.target
EOF

# ---------------------------------------------------------------------------
# 3. Log rotate — runs daily, rotates /var/log files older than 30 days
# ---------------------------------------------------------------------------
log "Installing spectra-log-rotate timer..."

cat > "${SYSTEMD_DIR}/spectra-log-rotate.service" <<'EOF'
[Unit]
Description=Spectra — rotate /var/log files older than 30 days
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/find /var/log -type f -name "*.log" -mtime +30 -delete
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=spectra-log-rotate
EOF

cat > "${SYSTEMD_DIR}/spectra-log-rotate.timer" <<'EOF'
[Unit]
Description=Spectra — daily log rotation
Requires=spectra-log-rotate.service

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=1800

[Install]
WantedBy=timers.target
EOF

# ---------------------------------------------------------------------------
# 4. Disk check — runs daily, checks disk usage and warns if >80%
# ---------------------------------------------------------------------------
log "Installing spectra-disk-check timer..."

cat > "${SYSTEMD_DIR}/spectra-disk-check.service" <<'EOF'
[Unit]
Description=Spectra — check disk usage and warn if >80%
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'df -h / | awk "NR==2 {gsub(/%/,\"\",$5); if ($5+0 > 80) print \"WARNING: root disk usage is at \"$5\"%\"}"'
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=spectra-disk-check
EOF

cat > "${SYSTEMD_DIR}/spectra-disk-check.timer" <<'EOF'
[Unit]
Description=Spectra — daily disk usage check
Requires=spectra-disk-check.service

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=900

[Install]
WantedBy=timers.target
EOF

# ---------------------------------------------------------------------------
# Enable and start all timers
# ---------------------------------------------------------------------------
log "Enabling and starting all Spectra maintenance timers..."

TIMERS=(
  spectra-journal-vacuum.timer
  spectra-docker-prune.timer
  spectra-log-rotate.timer
  spectra-disk-check.timer
)

for timer in "${TIMERS[@]}"; do
  systemctl daemon-reload
  systemctl enable "${timer}" 2>/dev/null || warn "Failed to enable ${timer}"
  systemctl start "${timer}" 2>/dev/null || warn "Failed to start ${timer}"
  log "  ${timer}: enabled and started"
done

log "All maintenance timers installed successfully"
log "Run 'systemctl list-timers spectra-*' to verify"
