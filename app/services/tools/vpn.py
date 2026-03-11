"""VPN Management Service for Spectra Tools Container.

Manages WireGuard and OpenVPN connections in the tools container
so all security tool traffic routes through VPN tunnels.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.queue import PostgresJobQueue

logger = logging.getLogger("spectra.services.tools.vpn")

# Strict name pattern: alphanumeric + hyphens, 1-64 chars
_CONFIG_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$")

# Dangerous directives that allow arbitrary command execution
_DANGEROUS_OPENVPN_DIRECTIVES = frozenset({
    "up", "down", "client-connect", "client-disconnect",
    "learn-address", "auth-user-pass-verify", "tls-verify",
    "ipchange", "route-up", "route-pre-down", "script-security",
})

_VPN_EXTENSIONS = {"wireguard": ".conf", "openvpn": ".ovpn"}


def _validate_config_name(name: str) -> str:
    """Validate and return a safe config name."""
    if not _CONFIG_NAME_RE.match(name):
        raise ValueError(
            "Config name must be 1-64 chars, alphanumeric and hyphens only, "
            "starting with alphanumeric"
        )
    return name


def _validate_wireguard_config(content: str) -> None:
    """Validate WireGuard config has required sections."""
    if "[Interface]" not in content:
        raise ValueError("WireGuard config must contain [Interface] section")
    if "[Peer]" not in content:
        raise ValueError("WireGuard config must contain [Peer] section")


def _validate_openvpn_config(content: str) -> None:
    """Validate OpenVPN config has required directives and no dangerous ones."""
    if not re.search(r"^\s*remote\s+", content, re.MULTILINE):
        raise ValueError("OpenVPN config must contain a 'remote' directive")

    for line in content.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("#") or not stripped:
            continue
        parts = stripped.split()
        directive = parts[0] if parts else ""
        if directive in _DANGEROUS_OPENVPN_DIRECTIVES:
            raise ValueError(
                f"OpenVPN config contains forbidden directive: '{directive}'. "
                "Embedded scripts are not allowed for security reasons."
            )


class VPNManager:
    """Manages VPN connections in the tools container."""

    def __init__(self, config_dir: str | None = None):
        self.config_dir = Path(config_dir or settings.VPN_CONFIG_DIR)
        self._queue = PostgresJobQueue(queue_name="default")

    def _ensure_config_dir(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _config_path(self, name: str, vpn_type: str) -> Path:
        ext = _VPN_EXTENSIONS.get(vpn_type)
        if not ext:
            raise ValueError(f"Unsupported VPN type: {vpn_type}")
        return self.config_dir / f"{name}{ext}"

    def _detect_type(self, name: str) -> str | None:
        """Detect VPN type from existing config file extension."""
        for vpn_type, ext in _VPN_EXTENSIONS.items():
            if (self.config_dir / f"{name}{ext}").exists():
                return vpn_type
        return None

    async def upload_config(
        self, name: str, config_content: bytes, vpn_type: str
    ) -> dict[str, Any]:
        """Save a VPN config file after validation."""
        name = _validate_config_name(name)
        if vpn_type not in _VPN_EXTENSIONS:
            raise ValueError(f"vpn_type must be 'wireguard' or 'openvpn', got '{vpn_type}'")

        text = config_content.decode("utf-8", errors="replace")

        if vpn_type == "wireguard":
            _validate_wireguard_config(text)
        else:
            _validate_openvpn_config(text)

        import asyncio

        self._ensure_config_dir()
        path = self._config_path(name, vpn_type)
        await asyncio.to_thread(path.write_text, text, encoding="utf-8")
        # Restrict permissions
        await asyncio.to_thread(path.chmod, 0o600)

        logger.info("Saved VPN config '%s' (%s) at %s", name, vpn_type, path)
        return {
            "name": name,
            "type": vpn_type,
            "path": str(path),
            "size": len(config_content),
        }

    async def connect(self, config_name: str) -> dict[str, Any]:
        """Start VPN connection by enqueuing a job to the tools worker."""
        config_name = _validate_config_name(config_name)
        vpn_type = self._detect_type(config_name)
        if not vpn_type:
            raise ValueError(f"No config found for '{config_name}'")

        config_path = str(self._config_path(config_name, vpn_type))
        job_id = await self._queue.enqueue_job(
            "vpn_connect_job", config_path, vpn_type, _timeout=60
        )
        logger.info("Enqueued VPN connect job %s for %s (%s)", job_id, config_name, vpn_type)
        return {"job_id": job_id, "config": config_name, "type": vpn_type, "action": "connect"}

    async def disconnect(self, config_name: str) -> dict[str, Any]:
        """Stop VPN connection by enqueuing a job to the tools worker."""
        config_name = _validate_config_name(config_name)
        vpn_type = self._detect_type(config_name)
        if not vpn_type:
            raise ValueError(f"No config found for '{config_name}'")

        job_id = await self._queue.enqueue_job(
            "vpn_disconnect_job", config_name, vpn_type, _timeout=30
        )
        logger.info("Enqueued VPN disconnect job %s for %s", job_id, config_name)
        return {"job_id": job_id, "config": config_name, "type": vpn_type, "action": "disconnect"}

    async def status(self) -> dict[str, Any]:
        """Get VPN connection status by enqueuing a status check job."""
        job_id = await self._queue.enqueue_job("vpn_status_job", _timeout=15)
        return {"job_id": job_id, "action": "status"}

    async def list_configs(self) -> list[dict[str, Any]]:
        """List all saved VPN configurations."""
        self._ensure_config_dir()
        configs: list[dict[str, Any]] = []
        for vpn_type, ext in _VPN_EXTENSIONS.items():
            for path in sorted(self.config_dir.glob(f"*{ext}")):
                configs.append({
                    "name": path.stem,
                    "type": vpn_type,
                    "path": str(path),
                    "size": path.stat().st_size,
                })
        return configs

    async def delete_config(self, name: str) -> bool:
        """Delete a saved VPN config file."""
        name = _validate_config_name(name)
        for ext in _VPN_EXTENSIONS.values():
            path = self.config_dir / f"{name}{ext}"
            if path.exists():
                path.unlink()
                logger.info("Deleted VPN config: %s", path)
                return True
        return False

    async def test_connection(self) -> dict[str, Any]:
        """Test VPN connectivity by enqueuing a test job."""
        job_id = await self._queue.enqueue_job("vpn_test_job", _timeout=30)
        return {"job_id": job_id, "action": "test"}
