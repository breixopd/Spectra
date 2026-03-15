"""VPN connection management jobs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .helpers import _run_command

logger = logging.getLogger(__name__)


async def vpn_connect_job(config_path: str, vpn_type: str) -> dict[str, Any]:
    """Start a VPN connection inside the tools container."""
    logger.info("VPN connect: %s (%s)", config_path, vpn_type)
    try:
        if vpn_type == "wireguard":
            cmd = f"wg-quick up {config_path}"
        elif vpn_type == "openvpn":
            name = Path(config_path).stem
            pid_file = f"/run/openvpn_{name}.pid"
            cmd = f"openvpn --daemon --config {config_path} --writepid {pid_file}"
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


async def vpn_disconnect_job(config_name: str, vpn_type: str) -> dict[str, Any]:
    """Stop a VPN connection inside the tools container."""
    logger.info("VPN disconnect: %s (%s)", config_name, vpn_type)
    try:
        if vpn_type == "wireguard":
            from app.core.config import settings as _s

            config_path = f"{_s.VPN_CONFIG_DIR}/{config_name}.conf"
            cmd = f"wg-quick down {config_path}"
        elif vpn_type == "openvpn":
            pid_file = f"/run/openvpn_{config_name}.pid"
            cmd = f"test -f {pid_file} && kill $(cat {pid_file}) && rm -f {pid_file} || echo 'no pid file'"
        else:
            return {"success": False, "error": f"Unknown VPN type: {vpn_type}"}

        returncode, stdout, stderr = await _run_command(cmd, 15)
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
        rc_wg, out_wg, _ = await _run_command("ip link show type wireguard 2>/dev/null", 5)
        if rc_wg == 0 and out_wg.strip():
            result["connected"] = True
            result["type"] = "wireguard"
            result["interface"] = "wg0"
            result["interfaces"].append("wg0")

        rc_tun, out_tun, _ = await _run_command("ip link show tun0 2>/dev/null", 5)
        if rc_tun == 0 and out_tun.strip():
            result["connected"] = True
            result.setdefault("type", "openvpn")
            result["interface"] = result.get("interface", "tun0")
            result["interfaces"].append("tun0")

        if result["connected"]:
            rc_ip, out_ip, _ = await _run_command(
                "curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo unknown", 10
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
        rc, stdout, stderr = await _run_command("curl -s --max-time 10 https://ifconfig.me 2>/dev/null", 15)
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
