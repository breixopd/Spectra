#!/usr/bin/env bash
# scripts/ops/install-maintenance-timers.sh — Install systemd timers for automated host maintenance
# Usage: sudo ./scripts/ops/install-maintenance-timers.sh
#
# Installs four timer units:
#   spectra-journal-vacuum  — weekly, vacuum systemd journals older than 14 days
#   spectra-docker-prune    — weekly, prune only managed Docker images/containers
#   spectra-log-rotate      — daily, run the host's configured logrotate policy
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
# 2. Docker prune — runs weekly, prunes only Spectra-managed images/containers.
#    Volumes are deliberately excluded: database, object-storage, and operator data
#    must never be removed by an unattended maintenance timer.
# ---------------------------------------------------------------------------
log "Installing spectra-docker-prune timer..."

cat > "${SYSTEMD_DIR}/spectra-docker-prune.service" <<'EOF'
[Unit]
Description=Spectra — prune managed Docker images and containers
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
# Keep other Docker projects and all volumes untouched. Compose and first-party
# images carry this label; unlabelled images are retained for safety. Docker
# build cache has no project-label filter, so it is intentionally not pruned by
# this unattended timer; use host-maintenance.sh with PRUNE_BUILDER_CACHE=1 on
# a dedicated host when a global cache prune is explicitly acceptable.
ExecStart=/usr/bin/docker container prune -f --filter label=spectra.managed=true --filter until=168h
ExecStart=/usr/bin/docker image prune -af --filter label=spectra.managed=true --filter until=168h
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
# 3. Log rotate — runs daily using the system's configured logrotate policy.
#    Never recursively delete arbitrary files under /var/log: package-specific
#    rotation rules handle ownership, compression, retention, and service reloads.
# ---------------------------------------------------------------------------
log "Installing spectra-log-rotate timer..."

cat > "${SYSTEMD_DIR}/spectra-log-rotate.service" <<'EOF'
[Unit]
Description=Spectra — run configured logrotate policy
After=local-fs.target
ConditionPathExists=/etc/logrotate.conf
ConditionFileIsExecutable=/usr/sbin/logrotate

[Service]
Type=oneshot
ExecStart=/usr/sbin/logrotate /etc/logrotate.conf
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
