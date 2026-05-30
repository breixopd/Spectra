"""VPN Management Service for Spectra Tools Container.

Manages WireGuard and OpenVPN connections in the tools container
so all security tool traffic routes through VPN tunnels.
VPN configs are stored in S3 (Garage) and downloaded to local temp for worker use.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from spectra_common.config import settings
from spectra_domain.jobs import WorkerJobName
from spectra_infra.queue import PostgresJobQueue
from spectra_storage_policy.storage import get_storage_service

logger = logging.getLogger(__name__)

# Strict name pattern: start alphanumeric, then alphanumeric/underscore/hyphen, 1-160 chars
_CONFIG_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,159}$")

# Dangerous directives that allow arbitrary command execution
_DANGEROUS_OPENVPN_DIRECTIVES = frozenset(
    {
        "up",
        "down",
        "client-connect",
        "client-disconnect",
        "learn-address",
        "auth-user-pass-verify",
        "tls-verify",
        "ipchange",
        "route-up",
        "route-pre-down",
        "script-security",
    }
)

# Dangerous WireGuard directives that allow arbitrary command execution or routing manipulation
_WIREGUARD_DANGEROUS_DIRECTIVES = frozenset({
    "postup", "postdown", "predown", "saveconfig",
    "dns", "table", "fwmark",  # Can manipulate routing
})

_VPN_EXTENSIONS = {"wireguard": ".conf", "openvpn": ".ovpn"}


def _validate_config_name(name: str) -> str:
    """Validate and return a safe config name."""
    if not _CONFIG_NAME_RE.match(name):
        raise ValueError(
            "Config name must be 1-160 chars, start with an alphanumeric, "
            "and contain only letters, numbers, underscores, or hyphens"
        )
    return name


def _validate_wireguard_config(content: str) -> None:
    """Validate WireGuard config has required sections and no dangerous directives."""
    if "[Interface]" not in content:
        raise ValueError("WireGuard config must contain [Interface] section")
    if "[Peer]" not in content:
        raise ValueError("WireGuard config must contain [Peer] section")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "[")):
            continue
        key = stripped.split("=", 1)[0].strip().lower()
        if key in _WIREGUARD_DANGEROUS_DIRECTIVES:
            raise ValueError(f"Dangerous WireGuard directive blocked: {key}")


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
    """Manages VPN connections in the tools container.

    Configs are stored in S3 under the ``vpn/`` prefix and downloaded to a
    local temp directory when workers or sandboxes need filesystem access.
    """

    def __init__(self, config_dir: str | None = None):
        self.config_dir = Path(config_dir or tempfile.mkdtemp(prefix="spectra_vpn_configs_"))
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._bucket = settings.S3_BUCKET_VPN
        self._prefix = "vpn/"
        self._queue = PostgresJobQueue(queue_name="default")

    def _s3_key(self, name: str, ext: str) -> str:
        return f"{self._prefix}{name}{ext}"

    async def _detect_type(self, name: str) -> str | None:
        """Detect VPN type by checking S3 for known extensions."""
        storage = get_storage_service()
        for vpn_type, ext in _VPN_EXTENSIONS.items():
            key = self._s3_key(name, ext)
            if await storage.exists(self._bucket, key):
                return vpn_type
        return None

    async def _download_to_local(self, name: str) -> Path | None:
        """Download config from S3 to local temp for worker/sandbox use."""
        storage = get_storage_service()
        for ext in _VPN_EXTENSIONS.values():
            key = self._s3_key(name, ext)
            if await storage.exists(self._bucket, key):
                local_path = self.config_dir / f"{name}{ext}"
                await storage.download_file(self._bucket, key, str(local_path))
                local_path.chmod(0o600)
                return local_path
        return None

    async def upload_config(self, name: str, config_content: bytes, vpn_type: str) -> dict[str, Any]:
        """Save a VPN config to S3 after validation."""
        name = _validate_config_name(name)
        if vpn_type not in _VPN_EXTENSIONS:
            raise ValueError(f"vpn_type must be 'wireguard' or 'openvpn', got '{vpn_type}'")

        text = config_content.decode("utf-8", errors="replace")

        if vpn_type == "wireguard":
            _validate_wireguard_config(text)
        else:
            _validate_openvpn_config(text)

        ext = _VPN_EXTENSIONS[vpn_type]
        key = self._s3_key(name, ext)
        storage = get_storage_service()
        await storage.upload(self._bucket, key, config_content)

        logger.info("Saved VPN config '%s' (%s) to S3 key %s", name, vpn_type, key)
        return {
            "name": name,
            "type": vpn_type,
            "path": key,
            "size": len(config_content),
        }

    async def connect(self, config_name: str) -> dict[str, Any]:
        """Start VPN connection by enqueuing a job to the tools worker."""
        config_name = _validate_config_name(config_name)
        vpn_type = await self._detect_type(config_name)
        if not vpn_type:
            raise ValueError(f"No config found for '{config_name}'")

        local_path = await self._download_to_local(config_name)
        if not local_path:
            raise ValueError(f"Failed to download config for '{config_name}'")

        config_path = str(local_path)
        job_id = await self._queue.enqueue_job(WorkerJobName.VPN_CONNECT, config_path, vpn_type, _timeout=60)
        logger.info("Enqueued VPN connect job %s for %s (%s)", job_id, config_name, vpn_type)
        return {"job_id": job_id, "config": config_name, "type": vpn_type, "action": "connect"}

    async def disconnect(self, config_name: str) -> dict[str, Any]:
        """Stop VPN connection by enqueuing a job to the tools worker."""
        config_name = _validate_config_name(config_name)
        vpn_type = await self._detect_type(config_name)
        if not vpn_type:
            raise ValueError(f"No config found for '{config_name}'")

        # Download to local — wg-quick down needs the config file
        local_path = await self._download_to_local(config_name)
        config_path = str(local_path) if local_path else ""

        job_id = await self._queue.enqueue_job(
            WorkerJobName.VPN_DISCONNECT,
            config_name,
            vpn_type,
            config_path,
            _timeout=30,
        )
        logger.info("Enqueued VPN disconnect job %s for %s", job_id, config_name)
        return {"job_id": job_id, "config": config_name, "type": vpn_type, "action": "disconnect"}

    async def status(self) -> dict[str, Any]:
        """Get VPN connection status by enqueuing a status check job."""
        job_id = await self._queue.enqueue_job(WorkerJobName.VPN_STATUS, _timeout=15)
        return {"job_id": job_id, "action": "status"}

    async def list_configs(self) -> list[dict[str, Any]]:
        """List all saved VPN configurations from S3."""
        storage = get_storage_service()
        keys = await storage.list_objects(self._bucket, self._prefix)
        configs: list[dict[str, Any]] = []
        for key in keys:
            filename = key.removeprefix(self._prefix)
            if not filename:
                continue
            name = Path(filename).stem
            vpn_type = "wireguard" if filename.endswith(".conf") else "openvpn"
            configs.append(
                {
                    "name": name,
                    "type": vpn_type,
                    "path": key,
                    "size": 0,
                }
            )
        return configs

    async def delete_config(self, name: str) -> bool:
        """Delete a saved VPN config from S3."""
        name = _validate_config_name(name)
        storage = get_storage_service()
        for ext in _VPN_EXTENSIONS.values():
            key = self._s3_key(name, ext)
            if await storage.exists(self._bucket, key):
                await storage.delete(self._bucket, key)
                logger.info("Deleted VPN config from S3: %s", key)
                return True
        return False

    async def test_connection(self) -> dict[str, Any]:
        """Test VPN connectivity by enqueuing a test job."""
        job_id = await self._queue.enqueue_job(WorkerJobName.VPN_TEST, _timeout=30)
        return {"job_id": job_id, "action": "test"}
