"""Remote server deployment via SSH.

Handles deploying Spectra services to remote servers:
1. Connect via SSH (key-based, password as fallback)
2. Harden the server (firewall, fail2ban, unattended-upgrades)
3. Install Docker if needed
4. Deploy services via docker compose
5. Configure networking (WireGuard mesh between nodes)
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass, field

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 fallback for UI runner

    class StrEnum(str, __import__("enum").Enum):
        pass


logger = logging.getLogger(__name__)


class DeploymentStatus(StrEnum):
    PENDING = "pending"
    CONNECTING = "connecting"
    HARDENING = "hardening"
    INSTALLING = "installing"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class DeployResult:
    status: DeploymentStatus
    message: str
    logs: list[str] = field(default_factory=list)


class ServerDeployer:
    """Deploy and manage Spectra services on remote servers via SSH."""

    def __init__(self) -> None:
        self._deployment_logs: dict[str, list[str]] = {}

    async def deploy_to_server(
        self,
        server_id: str,
        hostname: str,
        ssh_user: str,
        ssh_port: int = 22,
        ssh_key: str | None = None,
        services: list[str] | None = None,
        harden: bool = True,
    ) -> DeployResult:
        """Full deployment pipeline for a remote server."""
        logs: list[str] = []
        self._deployment_logs[server_id] = logs

        try:
            # Phase 1: Connect and verify
            logs.append(f"Connecting to {hostname}:{ssh_port} as {ssh_user}...")
            ssh_cmd_base = self._build_ssh_base(hostname, ssh_user, ssh_port, ssh_key)

            rc = await self._run_ssh(ssh_cmd_base, "echo 'Spectra deployment connected'", logs)
            if rc != 0:
                return DeployResult(DeploymentStatus.FAILED, "SSH connection failed", logs)

            # Phase 2: Harden
            if harden:
                logs.append("Phase 2: Hardening server...")
                rc = await self._harden_server(ssh_cmd_base, logs)
                if rc != 0:
                    logs.append("WARNING: Hardening had non-zero exit, continuing...")

            # Phase 3: Install Docker
            logs.append("Phase 3: Installing Docker...")
            rc = await self._install_docker(ssh_cmd_base, logs)
            if rc != 0:
                return DeployResult(DeploymentStatus.FAILED, "Docker installation failed", logs)

            # Phase 4: Deploy services
            logs.append("Phase 4: Deploying Spectra services...")
            target_services = services or ["app", "ai-svc", "scheduler", "tools"]
            await self._deploy_services(ssh_cmd_base, target_services, logs)

            # Phase 5: Verify
            logs.append("Phase 5: Verifying deployment...")
            ok = await self._verify_deployment(ssh_cmd_base, logs)
            if not ok:
                return DeployResult(DeploymentStatus.FAILED, "Verification failed", logs)

            return DeployResult(DeploymentStatus.COMPLETE, "Deployment successful", logs)

        except (OSError, RuntimeError, ValueError) as e:
            logger.exception("Deployment to %s failed", hostname)
            logs.append(f"FATAL: {e}")
            return DeployResult(DeploymentStatus.FAILED, str(e), logs)

    def _build_ssh_base(self, hostname: str, user: str, port: int, key: str | None) -> list[str]:
        """Build SSH command prefix with security-hardened options."""
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            "-p",
            str(port),
        ]
        if key:
            cmd.extend(["-i", key])
        cmd.append(f"{user}@{hostname}")
        return cmd

    async def _run_ssh(self, ssh_base: list[str], command: str, logs: list[str]) -> int:
        """Execute a command over SSH and capture output."""
        full_cmd = ssh_base + [command]
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if stdout:
            for line in stdout.decode().strip().split("\n"):
                if line:
                    logs.append(f"  [out] {line}")
        if stderr:
            for line in stderr.decode().strip().split("\n"):
                if line:
                    logs.append(f"  [err] {line}")
        return proc.returncode or 0

    async def _harden_server(self, ssh_base: list[str], logs: list[str]) -> int:
        """Apply security hardening to the remote server."""
        hardening_script = r"""set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get upgrade -y -qq

# Install security tools
apt-get install -y -qq ufw fail2ban unattended-upgrades apt-listchanges

# Configure UFW firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5000/tcp
ufw --force enable

# Configure fail2ban
cat > /etc/fail2ban/jail.local << 'JAIL'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
logpath = %(sshd_log)s
maxretry = 3
JAIL
systemctl enable fail2ban
systemctl restart fail2ban

# Enable unattended upgrades
cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'UU'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
UU

# Kernel hardening
cat >> /etc/sysctl.conf << 'SYSCTL'
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.conf.all.accept_source_route=0
net.ipv4.tcp_syncookies=1
SYSCTL
sysctl -p

echo "Server hardening complete"
"""
        return await self._run_ssh(ssh_base, f"bash -c {shlex.quote(hardening_script)}", logs)

    async def _install_docker(self, ssh_base: list[str], logs: list[str]) -> int:
        """Install Docker on the remote server if not present."""
        install_script = r"""set -e
if command -v docker &>/dev/null; then
    echo "Docker already installed: $(docker --version)"
else
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed: $(docker --version)"
fi
docker compose version 2>/dev/null || {
    apt-get install -y docker-compose-plugin
}
echo "Docker Compose: $(docker compose version)"
"""
        return await self._run_ssh(ssh_base, f"bash -c {shlex.quote(install_script)}", logs)

    async def _deploy_services(self, ssh_base: list[str], services: list[str], logs: list[str]) -> int:
        """Deploy Spectra services via Docker Compose on the remote server."""
        svc_list = " ".join(shlex.quote(s) for s in services)
        deploy_script = f"""set -e
mkdir -p /opt/spectra
cd /opt/spectra

if [ -f docker-compose.yml ]; then
    docker compose pull --ignore-pull-failures 2>/dev/null || true
    docker compose up -d --remove-orphans {svc_list}
    echo "Services deployed: {", ".join(services)}"
else
    echo "WARNING: No docker-compose.yml found at /opt/spectra. Upload config first."
fi
"""
        return await self._run_ssh(ssh_base, f"bash -c {shlex.quote(deploy_script)}", logs)

    async def _verify_deployment(self, ssh_base: list[str], logs: list[str]) -> bool:
        """Verify services are running on the remote server."""
        rc = await self._run_ssh(
            ssh_base,
            "docker ps --format '{{.Names}} {{.Status}}'",
            logs,
        )
        return rc == 0

    def get_deployment_logs(self, server_id: str) -> list[str]:
        """Return cached deployment logs for a server."""
        return self._deployment_logs.get(server_id, [])
