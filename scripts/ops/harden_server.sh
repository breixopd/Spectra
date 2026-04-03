#!/usr/bin/env bash
# scripts/ops/harden_server.sh — Automated server hardening for Spectra nodes
# Usage: ./scripts/ops/harden_server.sh [OPTIONS]
#   --yes          Skip confirmation prompt
#   --ssh-port N   Custom SSH port (default: 22)
#   --user USER    App user to create (default: spectra)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[harden]"
SSH_PORT="${SSH_PORT:-22}"
APP_USER="${APP_USER:-spectra}"
CONFIRM=""

log()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) $*"; }
warn() { echo "${LOG_PREFIX} $(date +%H:%M:%S) [WARN] $*" >&2; }
die()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) [FATAL] $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y|--force) CONFIRM="yes"; shift;;
    --ssh-port) SSH_PORT="$2"; shift 2;;
    --user) APP_USER="$2"; shift 2;;
    *) die "Unknown option: $1";;
  esac
done

[[ "$(id -u)" -eq 0 ]] || die "Must run as root"

if [[ "${CONFIRM}" != "yes" ]]; then
  echo "This will apply security hardening to this server."
  echo "Changes: SSH hardening, firewall, fail2ban, sysctl, auto-updates"
  read -rp "Continue? [y/N] " answer
  [[ "${answer,,}" == "y" ]] || exit 0
fi

# 1. System updates
log "Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

# 2. Install security packages
log "Installing security packages..."
apt-get install -y -qq ufw fail2ban unattended-upgrades apt-listchanges

# 3. Create app user
if ! id "${APP_USER}" &>/dev/null; then
  log "Creating app user: ${APP_USER}"
  useradd -r -m -s /bin/bash "${APP_USER}"
  usermod -aG docker "${APP_USER}" 2>/dev/null || true
fi

# 4. SSH hardening
log "Hardening SSH (port ${SSH_PORT})..."
SSHD_CONFIG="/etc/ssh/sshd_config"
cp "${SSHD_CONFIG}" "${SSHD_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"

# Apply SSH hardening settings
cat > /etc/ssh/sshd_config.d/99-spectra-hardening.conf <<SSHEOF
Port ${SSH_PORT}
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
AllowAgentForwarding no
AllowTcpForwarding no
SSHEOF

# 5. Firewall (UFW)
log "Configuring firewall..."
ufw --force reset >/dev/null 2>&1
ufw default deny incoming
ufw default allow outgoing
ufw allow "${SSH_PORT}/tcp" comment "SSH"
ufw allow 80/tcp comment "HTTP"
ufw allow 443/tcp comment "HTTPS"
ufw allow 2377/tcp comment "Docker Swarm management"
ufw allow 7946/tcp comment "Docker Swarm node communication"
ufw allow 7946/udp comment "Docker Swarm node communication"
ufw allow 4789/udp comment "Docker overlay network"
ufw --force enable
log "Firewall enabled"

# 6. Fail2ban
log "Configuring fail2ban..."
cat > /etc/fail2ban/jail.d/spectra.conf <<F2BEOF
[sshd]
enabled = true
port = ${SSH_PORT}
maxretry = 5
bantime = 3600
findtime = 600

[docker-abuse]
enabled = true
filter = docker-abuse
logpath = /var/log/syslog
maxretry = 10
bantime = 3600
F2BEOF

# Create docker abuse filter
cat > /etc/fail2ban/filter.d/docker-abuse.conf <<FILTEREOF
[Definition]
failregex = .*Docker.*refused connection from <HOST>
ignoreregex =
FILTEREOF

systemctl enable fail2ban
systemctl restart fail2ban

# 7. Sysctl hardening
log "Applying kernel hardening..."
cat > /etc/sysctl.d/99-spectra-hardening.conf <<SYSCTLEOF
# Network hardening
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048

# IPv6 hardening
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0

# Kernel hardening
kernel.randomize_va_space = 2
kernel.kptr_restrict = 2
kernel.yama.ptrace_scope = 1
fs.suid_dumpable = 0

# Docker / container optimisation
net.ipv4.ip_forward = 1
vm.overcommit_memory = 1
net.core.somaxconn = 65535
SYSCTLEOF

sysctl --system >/dev/null 2>&1

# 8. Automatic security updates
log "Enabling automatic security updates..."
cat > /etc/apt/apt.conf.d/20auto-upgrades <<AUTOEOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
AUTOEOF

cat > /etc/apt/apt.conf.d/50unattended-upgrades <<UNATTEOF
Unattended-Upgrade::Allowed-Origins {
    "\${distro_id}:\${distro_codename}-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
UNATTEOF

# 9. Restart SSH
log "Restarting SSH..."
systemctl restart sshd || systemctl restart ssh

log "Server hardening complete"
log "Summary:"
log "  SSH port: ${SSH_PORT}"
log "  Root login: prohibit-password (keys only)"
log "  Password auth: disabled"
log "  Firewall: enabled (SSH, HTTP, HTTPS, Swarm ports)"
log "  Fail2ban: enabled (SSH + Docker abuse)"
log "  Auto-updates: enabled (security only)"
log "  Sysctl: hardened (network, kernel)"
log ""
log "IMPORTANT: Ensure your SSH key is in ~/.ssh/authorized_keys"
log "           before closing this session!"
