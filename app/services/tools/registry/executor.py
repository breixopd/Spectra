"""
Command Executor for Tool Installation.

This module runs shell commands for tool installation.
It ONLY runs in the tools container - no docker exec wrapping.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import signal
from typing import TYPE_CHECKING

from app.services.tools.registry.constants import MAX_OUTPUT_SIZE

if TYPE_CHECKING:
    from asyncio import StreamReader

logger = logging.getLogger(__name__)

_ROOT_REQUIRED_TOKENS = (
    "apt-get",
    "apt ",
    "dpkg ",
)


def _needs_privilege_elevation(command: str) -> bool:
    lowered = f" {command.strip().lower()} "
    return any(token in lowered for token in _ROOT_REQUIRED_TOKENS)


def _prepare_command(command: str) -> str:
    stripped = command.strip()
    if not stripped:
        return stripped
    if stripped.startswith("sudo "):
        return stripped
    if _needs_privilege_elevation(stripped):
        return f"sudo -n bash -lc {shlex.quote(stripped)}"
    return stripped


async def run_command_safe(command: str, timeout: int = 300) -> tuple[int, str, str]:
    """
    Execute a shell command asynchronously with a timeout.

    This function runs commands directly (no docker exec wrapping).
    It should ONLY be called from the tools container via ARQ worker.

    Args:
        command: The shell command to execute.
        timeout: Maximum seconds to wait for completion.

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    if not command or not command.strip():
        return (-1, "", "Empty command provided")

    # Setup environment
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    # Ensure /opt/spectra_tools is in PATH for installed binaries
    env["PATH"] = f"/opt/spectra_tools:{env.get('PATH', '')}"

    logger.debug("Executing: %s", command[:200])
    prepared_command = _prepare_command(command)
    logger.debug("Executing: %s", prepared_command[:200])

    try:
        proc = await asyncio.create_subprocess_shell(
            prepared_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
    except (OSError, RuntimeError, ValueError) as e:
        logger.error("Failed to start subprocess: %s", e)
        return (-1, "", str(e))

    stdout_task = None
    stderr_task = None

    try:
        if not proc.stdout or not proc.stderr:
            return (-1, "", "Failed to capture stdout/stderr")

        stdout_task = asyncio.create_task(_read_stream_limit(proc.stdout))
        stderr_task = asyncio.create_task(_read_stream_limit(proc.stderr))

        await asyncio.wait_for(proc.wait(), timeout=timeout)

        stdout_str = await stdout_task
        stderr_str = await stderr_task

        return (
            proc.returncode if proc.returncode is not None else -1,
            stdout_str,
            stderr_str,
        )

    except TimeoutError:
        # Cancel stream readers
        for task in (stdout_task, stderr_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Kill the entire process group
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

        await proc.wait()

        return (-1, "", f"Command timed out after {timeout}s")

    except (OSError, RuntimeError, ValueError) as e:
        # Clean up on any other error
        for task in (stdout_task, stderr_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        try:
            proc.kill()
        except ProcessLookupError:
            pass

        await proc.wait()

        logger.error("Command execution failed: %s", e)
        return (-1, "", str(e))


async def _read_stream_limit(stream: StreamReader) -> str:
    """Read from stream with size limit to prevent memory issues."""
    chunks = []
    total_size = 0

    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break

        total_size += len(chunk)
        if total_size <= MAX_OUTPUT_SIZE:
            chunks.append(chunk)
        else:
            # Truncate if too large
            if chunks:
                chunks.append(b"\n... (output truncated)")
            break

    return b"".join(chunks).decode("utf-8", errors="replace")
