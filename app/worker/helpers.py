"""Worker internal helpers: command execution, status tracking, error formatting."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from app.core.constants import HTTP_CLIENT_MAX_RETRIES

logger = logging.getLogger(__name__)
TOOLS_PATH_PREFIX = "/opt/spectra_tools"


def with_retry(max_retries: int = HTTP_CLIENT_MAX_RETRIES, backoff_base: float = 2.0, max_backoff: float = 60.0):
    """Decorator adding exponential backoff retry to async worker jobs."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    raise
                except (OSError, RuntimeError, ValueError) as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = min(backoff_base**attempt, max_backoff)
                        logger.warning(
                            "Job %s attempt %d/%d failed, retrying in %.1fs: %s",
                            func.__name__,
                            attempt,
                            max_retries,
                            wait,
                            exc,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error("Job %s failed after %d attempts: %s", func.__name__, max_retries, exc)
            raise last_exc  # type: ignore[misc]  # last_exc is always set after loop

        return wrapper

    return decorator


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
    return bool(persistence_path.exists() and os.access(persistence_path, os.X_OK))


def _build_process_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["PATH"] = f"{TOOLS_PATH_PREFIX}:{env.get('PATH', '')}"
    return env


def _decode_process_output(output: bytes) -> str:
    return output.decode("utf-8", errors="replace")


async def _start_process(
    command: str | list[str],
    cwd: str | None,
    env: dict[str, str],
):
    """Start a subprocess for command execution.

    When *command* is a ``list``, ``create_subprocess_exec`` is used (no shell).
    When *command* is a ``str``, ``create_subprocess_shell`` is **intentionally**
    kept because callers (tool_jobs, command_jobs) build command strings that rely
    on shell features such as ``timeout … cmd`` wrapping and tool-specific
    pipelines / redirects.  All user-controlled fragments that are interpolated
    into these strings MUST be escaped with ``shlex.quote()`` at the call-site.
    """
    if isinstance(command, list):
        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )

    return await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )


async def _run_command(
    command: str | list[str],
    timeout: int,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run a shell command with timeout."""
    env = _build_process_env()

    try:
        proc = await _start_process(command, cwd, env)
    except (OSError, ValueError) as e:
        logger.error("Failed to start process: %s", e)
        return (-1, "", str(e))

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        return (
            proc.returncode or 0,
            _decode_process_output(stdout_bytes),
            _decode_process_output(stderr_bytes),
        )
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
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
    except (OSError, RuntimeError, ConnectionError, ValueError) as e:
        logger.warning("Failed to track tool stats for %s: %s", tool_id, e)


def _status_field(
    result: dict[str, Any],
    existing: dict[str, Any],
    key: str,
) -> str:
    return str(result.get(key) or existing.get(key) or "")


def _merge_status_logs(existing_logs: Any, log_entry: Any) -> list[str]:
    logs = existing_logs if isinstance(existing_logs, list) else []
    if isinstance(log_entry, str) and log_entry.strip():
        return [*logs, f"{datetime.now().isoformat()} {log_entry.strip()}"][-40:]
    return logs


def _build_tool_status_payload(
    existing: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": str(result.get("status") or "unknown"),
        "last_updated": datetime.now().isoformat(),
        "error": str(result.get("error") or ""),
        "message": _status_field(result, existing, "message"),
        "phase": _status_field(result, existing, "phase"),
        "command": _status_field(result, existing, "command"),
        "last_output": _status_field(result, existing, "last_output"),
        "command_index": result.get("command_index"),
        "logs": _merge_status_logs(existing.get("logs"), result.get("log_entry")),
    }


async def _sync_tool_status(
    tool_id: str,
    result: dict[str, Any],
) -> None:
    """Sync tool status to PostgreSQL cache."""
    from app.core.cache import CacheService

    cache = CacheService()
    key = f"spectra:tool_status:{tool_id}"
    existing = await cache.get(key)
    if not isinstance(existing, dict):
        existing = {}

    await cache.set(
        key,
        _build_tool_status_payload(existing, result),
        ttl=3600,  # 1 hour
    )
