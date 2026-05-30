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
import ipaddress
import logging
import re
import shlex
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from spectra_common.paths import data_path

logger = logging.getLogger(__name__)

DOCKER_APT_REPO_SIGNING_FINGERPRINT = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"

_VALID_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.(?!-)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$"
)


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
        pinned_known_host: str | None = None,
        services: list[str] | None = None,
        harden: bool = True,
    ) -> DeployResult:
        """Full deployment pipeline for a remote server."""
        logs: list[str] = []
        self._deployment_logs[server_id] = logs

        try:
            # Phase 1: Connect and verify
            logs.append(f"Connecting to {hostname}:{ssh_port} as {ssh_user}...")
            known_hosts_path = await self._ensure_known_host(hostname, ssh_port, pinned_known_host)
            ssh_cmd_base = self._build_ssh_base(hostname, ssh_user, ssh_port, ssh_key, known_hosts_path)

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
            rc = await self._deploy_services(ssh_cmd_base, target_services, logs)
            if rc != 0:
                return DeployResult(DeploymentStatus.FAILED, "Service deployment failed", logs)

            # Phase 5: Verify
            logs.append("Phase 5: Verifying deployment...")
            ok = await self._verify_deployment(ssh_cmd_base, target_services, logs)
            if not ok:
                return DeployResult(DeploymentStatus.FAILED, "Verification failed", logs)

            return DeployResult(DeploymentStatus.COMPLETE, "Deployment successful", logs)

        except (OSError, RuntimeError, ValueError) as e:
            logger.exception("Deployment to %s failed", hostname)
            logs.append(f"FATAL: {e}")
            return DeployResult(DeploymentStatus.FAILED, str(e), logs)

    def _known_hosts_path(self) -> Path:
        """Return the local known_hosts file used for deploy-time SSH trust."""
        return data_path("config", "deployer_known_hosts")

    @staticmethod
    def _known_hosts_target(hostname: str, port: int) -> str:
        return hostname if port == 22 else f"[{hostname}]:{port}"

    @staticmethod
    def _line_matches_known_host(line: str, expected_host: str) -> bool:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return False
        host_field = stripped.split()[0]
        host_tokens = {token.strip() for token in host_field.split(",")}
        return expected_host in host_tokens

    @staticmethod
    def _normalize_known_host_lines(entry: str) -> list[str]:
        lines: list[str] = []
        for raw_line in entry.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped not in lines:
                lines.append(stripped)
        return lines

    @staticmethod
    def _validate_scan_target(hostname: str, port: int) -> str:
        candidate = hostname.strip()
        if candidate != hostname or not candidate:
            raise ValueError("SSH hostname must be a non-empty host or IP address")
        if not 1 <= port <= 65535:
            raise ValueError(f"SSH port must be between 1 and 65535, got {port}")
        if candidate.startswith("-"):
            raise ValueError(f"Invalid SSH hostname: {hostname!r}")

        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            if not _VALID_HOSTNAME_RE.fullmatch(candidate):
                raise ValueError(f"Invalid SSH hostname: {hostname!r}") from None

        return candidate

    @staticmethod
    def _ssh_keyscan_executable() -> str:
        executable = shutil.which("ssh-keyscan")
        if executable is None:
            raise RuntimeError("ssh-keyscan executable not found in PATH")
        return executable

    async def _ensure_known_host(self, hostname: str, port: int, pinned_known_host: str | None = None) -> Path:
        """Ensure deploy-time SSH trust is pinned locally before connecting."""
        known_hosts_path = self._known_hosts_path()
        await asyncio.to_thread(known_hosts_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(known_hosts_path.touch, exist_ok=True)
        await asyncio.to_thread(known_hosts_path.chmod, 0o600)

        existing_text = await asyncio.to_thread(known_hosts_path.read_text, encoding="utf-8")
        existing_lines = existing_text.splitlines()
        expected_host = self._known_hosts_target(hostname, port)

        if pinned_known_host is not None:
            pinned_lines = self._normalize_known_host_lines(pinned_known_host)
            if not pinned_lines:
                raise ValueError(f"Pinned known-host entry for {hostname}:{port} is empty")

            retained_lines = [
                line for line in existing_lines if not self._line_matches_known_host(line, expected_host)
            ]
            merged_lines = list(dict.fromkeys([*retained_lines, *pinned_lines]))
            await asyncio.to_thread(
                known_hosts_path.write_text,
                "\n".join(merged_lines) + "\n",
                encoding="utf-8",
            )
            logger.info("Persisted pinned SSH host key for %s:%s", hostname, port)
            return known_hosts_path

        for line in existing_lines:
            if self._line_matches_known_host(line, expected_host):
                return known_hosts_path

        scan_host = self._validate_scan_target(hostname, port)
        ssh_keyscan = self._ssh_keyscan_executable()

        try:
            # The host and port are validated, and the executable path is fully resolved.
            proc = await asyncio.create_subprocess_exec(
                ssh_keyscan,
                "-p",
                str(port),
                scan_host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                detail = (stderr_data.decode("utf-8", errors="replace").strip() or "no error output")
                raise RuntimeError(
                    f"ssh-keyscan failed for {hostname}:{port}: {detail}"
                )
        except TimeoutError as exc:
            raise RuntimeError(
                f"ssh-keyscan timed out for {hostname}:{port}"
            ) from exc
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            detail = str(exc).strip() or "no error output"
            raise RuntimeError(
                f"ssh-keyscan failed for {hostname}:{port}: {detail}"
            ) from exc

        scanned_lines = self._normalize_known_host_lines(stdout_data.decode("utf-8", errors="replace"))
        if not scanned_lines:
            raise RuntimeError(f"ssh-keyscan returned no host keys for {hostname}:{port}")

        def _append_lines() -> None:
            with known_hosts_path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(scanned_lines))
                handle.write("\n")

        await asyncio.to_thread(_append_lines)

        logger.info(
            "Trusted new deploy SSH host key on first use for %s:%s using %s",
            hostname,
            port,
            known_hosts_path,
        )
        return known_hosts_path

    def _build_ssh_base(
        self,
        hostname: str,
        user: str,
        port: int,
        key: str | None,
        known_hosts_path: Path,
    ) -> list[str]:
        """Build SSH command prefix with security-hardened options."""
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts_path}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
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
        full_cmd = [*ssh_base, command]
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
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    docker_key_tmp="$(mktemp)"
    trap 'rm -f "${docker_key_tmp}"' EXIT
    curl -fsSL "https://download.docker.com/linux/$(. /etc/os-release && echo "${ID}")/gpg" -o "${docker_key_tmp}"
    docker_key_fingerprint="$(gpg --batch --show-keys --with-colons "${docker_key_tmp}" | awk -F: '/^fpr:/ {print $10; exit}')"
    if [ "${docker_key_fingerprint}" != "@@DOCKER_FINGERPRINT@@" ]; then
        echo "Unexpected Docker signing key fingerprint: ${docker_key_fingerprint}" >&2
        exit 1
    fi
    gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg "${docker_key_tmp}"
    chmod a+r /etc/apt/keyrings/docker.gpg
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME:-$UBUNTU_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    echo "Docker installed: $(docker --version)"
fi
systemctl enable docker
systemctl start docker
docker compose version >/dev/null 2>&1 || {
    apt-get update -qq
    apt-get install -y -qq docker-compose-plugin
}
echo "Docker Compose: $(docker compose version)"
"""
        install_script = install_script.replace("@@DOCKER_FINGERPRINT@@", DOCKER_APT_REPO_SIGNING_FINGERPRINT)
        return await self._run_ssh(ssh_base, f"bash -c {shlex.quote(install_script)}", logs)

    async def _deploy_services(self, ssh_base: list[str], services: list[str], logs: list[str]) -> int:
        """Deploy Spectra services via Docker Compose on the remote server."""
        svc_list = " ".join(shlex.quote(s) for s in services)
        deploy_script = f"""set -e
mkdir -p /opt/spectra
cd /opt/spectra

COMPOSE_FILE="deploy/docker/compose.yaml"
if [ -f "$COMPOSE_FILE" ]; then
    docker compose -f "$COMPOSE_FILE" --profile app pull --ignore-pull-failures 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" --profile app up -d --remove-orphans {svc_list}
    echo "Services deployed: {", ".join(services)}"
else
    echo "ERROR: No deploy/docker/compose.yaml found at /opt/spectra. Upload config first." >&2
    exit 1
fi
"""
        return await self._run_ssh(ssh_base, f"bash -c {shlex.quote(deploy_script)}", logs)

    async def _verify_deployment(self, ssh_base: list[str], services: list[str], logs: list[str]) -> bool:
        """Verify services are running on the remote server."""
        svc_list = " ".join(shlex.quote(service) for service in services)
        verify_script = f"""set -e
cd /opt/spectra

COMPOSE_FILE="deploy/docker/compose.yaml"
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "ERROR: Missing /opt/spectra/deploy/docker/compose.yaml during verification." >&2
    exit 1
fi

running_services="$(docker compose -f "$COMPOSE_FILE" --profile app ps --services --status running)"
if [ -n "$running_services" ]; then
    echo "Running compose services:"
    printf '%s\n' "$running_services"
else
    echo "Running compose services: none"
fi

missing_services=""
for service in {svc_list}; do
    if ! printf '%s\n' "$running_services" | grep -Fxq "$service"; then
        missing_services="$missing_services $service"
    fi
done

if [ -n "$missing_services" ]; then
    echo "ERROR: Requested services not running:${{missing_services}}" >&2
    exit 1
fi

echo "Verified running services: {", ".join(services)}"
"""
        rc = await self._run_ssh(ssh_base, f"bash -c {shlex.quote(verify_script)}", logs)
        return rc == 0

    def get_deployment_logs(self, server_id: str) -> list[str]:
        """Return cached deployment logs for a server."""
        return self._deployment_logs.get(server_id, [])
