"""VPN connection management jobs."""

from __future__ import annotations

import logging
import os
import re
import signal as _signal
from pathlib import Path
from typing import Any

from .helpers import _run_command

logger = logging.getLogger(__name__)

# Allowlist pattern: letters, digits, underscore, hyphen, forward slash, dot only.
_SAFE_PATH_RE = re.compile(r'^[a-zA-Z0-9_\-/\.]+$')
# Safe config name (no path separators)
_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _validate_config_path(path: str) -> bool:
    """Return True if path contains only safe characters and has no path traversal."""
    return bool(_SAFE_PATH_RE.match(path)) and '..' not in path


def _validate_config_name(name: str) -> bool:
    """Return True if config name is a safe bare filename (no slashes or special chars)."""
    return bool(_SAFE_NAME_RE.match(name))


async def vpn_connect_job(config_path: str, vpn_type: str) -> dict[str, Any]:
    """Start a VPN connection inside the tools container."""
    logger.info("VPN connect: %s (%s)", config_path, vpn_type)

    if not _validate_config_path(config_path):
        logger.error("VPN connect rejected: invalid config_path %r", config_path)
        return {"success": False, "error": "Invalid config path"}

    try:
        if vpn_type == "wireguard":
            cmd: list[str] = ["wg-quick", "up", config_path]
        elif vpn_type == "openvpn":
            name = Path(config_path).stem
            pid_file = f"/run/openvpn_{name}.pid"
            cmd = ["openvpn", "--daemon", "--config", config_path, "--writepid", pid_file]
        else:
            return {"success": False, "error": f"Unknown VPN type: {vpn_type}"}

        returncode, stdout, stderr = await _run_command(cmd, 30)
        success = returncode == 0
        return {
            "success": success,
            "type": vpn_type,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": returncode,
        }
    except (OSError, RuntimeError, ValueError) as e:
        logger.error("VPN connect failed: %s", e)
        return {"success": False, "error": str(e)}


async def vpn_disconnect_job(config_name: str, vpn_type: str, config_path: str = "") -> dict[str, Any]:
    """Stop a VPN connection inside the tools container."""
    logger.info("VPN disconnect: %s (%s)", config_name, vpn_type)

    if not _validate_config_name(config_name):
        logger.error("VPN disconnect rejected: invalid config_name %r", config_name)
        return {"success": False, "error": "Invalid config name"}

    try:
        if vpn_type == "wireguard":
            if not config_path:
                config_path = f"/tmp/vpn_configs/{config_name}.conf"
            cmd: list[str] = ["wg-quick", "down", config_path]
            returncode, stdout, stderr = await _run_command(cmd, 15)
        elif vpn_type == "openvpn":
            pid_file_path = Path(f"/run/openvpn_{config_name}.pid")
            stdout = ""
            stderr = ""
            try:
                pid = int(pid_file_path.read_text().strip())
                os.kill(pid, _signal.SIGTERM)
                pid_file_path.unlink(missing_ok=True)
                stdout = "OpenVPN process terminated"
                returncode = 0
            except FileNotFoundError:
                stdout = "no pid file"
                returncode = 0
            except (ValueError, ProcessLookupError) as pid_err:
                stderr = str(pid_err)
                returncode = 1
        else:
            return {"success": False, "error": f"Unknown VPN type: {vpn_type}"}

        return {
            "success": returncode == 0,
            "type": vpn_type,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": returncode,
        }
    except (OSError, RuntimeError, ValueError) as e:
        logger.error("VPN disconnect failed: %s", e)
        return {"success": False, "error": str(e)}


async def vpn_status_job() -> dict[str, Any]:
    """Check VPN interface status inside the tools container."""
    result: dict[str, Any] = {"connected": False, "interfaces": []}
    try:
        rc_wg, out_wg, _ = await _run_command(["ip", "link", "show", "type", "wireguard"], 5)
        if rc_wg == 0 and out_wg.strip():
            result["connected"] = True
            result["type"] = "wireguard"
            result["interface"] = "wg0"
            result["interfaces"].append("wg0")

        rc_tun, out_tun, _ = await _run_command(["ip", "link", "show", "tun0"], 5)
        if rc_tun == 0 and out_tun.strip():
            result["connected"] = True
            result.setdefault("type", "openvpn")
            result["interface"] = result.get("interface", "tun0")
            result["interfaces"].append("tun0")

        if result["connected"]:
            rc_ip, out_ip, _ = await _run_command(
                ["curl", "-s", "--max-time", "5", "https://ifconfig.me"], 10
            )
            result["public_ip"] = out_ip.strip() if rc_ip == 0 else "unknown"

    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("VPN status check failed: %s", e)
        result["error"] = str(e)
    return result


async def vpn_test_job() -> dict[str, Any]:
    """Test VPN connectivity by checking the public IP."""
    logger.info("VPN connectivity test")
    try:
        rc, stdout, stderr = await _run_command(["curl", "-s", "--max-time", "10", "https://ifconfig.me"], 15)
        if rc == 0 and stdout.strip():
            return {
                "success": True,
                "public_ip": stdout.strip(),
                "message": "VPN connectivity confirmed",
            }
        return {
            "success": False,
            "public_ip": None,
            "message": f"Connectivity check failed: {stderr or 'no response'}",
        }
    except (OSError, RuntimeError, ValueError) as e:
        logger.error("VPN test failed: %s", e)
        return {"success": False, "error": str(e)}
