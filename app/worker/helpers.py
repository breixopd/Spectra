"""Worker internal helpers: command execution, status tracking, error formatting."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.tools.models import ToolStatus

logger = logging.getLogger("spectra.worker")


def _error_result(tool_id: str, target: str, error: str) -> dict[str, Any]:
    """Create an error result dict."""
    return {
        "tool_id": tool_id,
        "target": target,
        "success": False,
        "exit_code": -1,
        "stdout": "",
        "stderr": error,
        "duration_seconds": 0.0,
        "parsed_findings": [],
    }


def _get_executable(tool) -> str:
    """Get the executable name from a tool's command."""
    cmd_parts = tool.config.execution.command.split()
    return cmd_parts[0] if cmd_parts else tool.config.id


def _is_tool_installed(tool) -> bool:
    """Check if a tool is installed."""
    executable = _get_executable(tool)

    # Check if in PATH
    if shutil.which(executable):
        return True

    # Check persistence path
    persistence_path = Path("/opt/spectra_tools") / executable
    if persistence_path.exists() and os.access(persistence_path, os.X_OK):
        return True

    return False


async def _run_command(
    command: str | list[str],
    timeout: int,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run a shell command with timeout."""
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    # Ensure /opt/spectra_tools is in PATH
    env["PATH"] = f"/opt/spectra_tools:{env.get('PATH', '')}"

    try:
        if isinstance(command, list):
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
    except Exception as e:
        logger.error("Failed to start process: %s", e)
        return (-1, "", str(e))

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        return (
            proc.returncode or 0,
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
        )
    except TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        return (-1, "", f"Command timed out after {timeout}s")


async def _track_tool_stats(
    tool_id: str,
    success: bool,
    duration: float,
) -> None:
    """Track tool execution statistics via cache."""
    from app.core.cache import CacheService

    cache = CacheService()
    stats_key = f"spectra:tool_stats:{tool_id}"

    try:
        stats = await cache.get(stats_key) or {
            "success_count": 0,
            "fail_count": 0,
            "total_count": 0,
            "total_duration": 0.0,
        }
        stats["total_count"] += 1
        if success:
            stats["success_count"] += 1
        else:
            stats["fail_count"] += 1
        stats["total_duration"] += duration
        stats["last_run"] = datetime.now().isoformat()
        stats["last_duration"] = str(duration)
        await cache.set(stats_key, stats, ttl=604800)  # 7 days
    except Exception as e:
        logger.warning("Failed to track tool stats for %s: %s", tool_id, e)


async def _sync_tool_status(
    tool_id: str,
    result: dict[str, Any],
) -> None:
    """Sync tool status to PostgreSQL cache."""
    from app.core.cache import CacheService

    cache = CacheService()
    key = f"spectra:tool_status:{tool_id}"
    status = str(result.get("status") or "unknown")
    error = str(result.get("error") or "")

    await cache.set(
        key,
        {
            "status": status,
            "last_updated": datetime.now().isoformat(),
            "error": error,
        },
        ttl=3600,  # 1 hour
    )
