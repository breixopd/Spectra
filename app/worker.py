"""
ARQ Worker for Spectra Tools Container.

This worker runs ONLY inside the tools container and handles:
- Tool execution (runs commands directly, no docker exec)
- Tool installation/uninstallation
- Tool status syncing to Redis
- Background plugin installation when new plugins are uploaded

Architecture:
- App container enqueues jobs to Redis via ARQ
- This worker picks up jobs and executes them locally
- Results are returned via ARQ and status is synced to Redis
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import shutil
import signal
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.core.constants import (
    ARQ_HEALTH_CHECK_INTERVAL,
    ARQ_JOB_TIMEOUT,
    ARQ_KEEP_RESULT,
    ARQ_MAX_JOBS,
    ARQ_QUEUE_NAME,
    GO_COMPILE_TIMEOUT,
    MAX_HOSTS_DEFAULT,
)
from app.services.tools.models import (
    ToolStatus,
    ToolExecutionRequest,
    ToolExecutionResult,
)

logger = logging.getLogger("spectra.worker")


# =============================================================================
# Tool Execution Job
# =============================================================================


async def execute_tool_job(
    ctx: dict[str, Any],
    tool_id: str,
    target: str,
    args: dict[str, Any] | None = None,
    timeout: int | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """
    Execute a security tool locally in the tools container.

    Args:
        ctx: ARQ context with redis connection.
        tool_id: ID of the tool to run.
        target: Target for the tool.
        args: Additional arguments.
        timeout: Timeout override.
        output_dir: Directory for output files.

    Returns:
        ToolExecutionResult as dict.
    """
    from app.services.tools.registry import get_registry
    from app.services.tools.adapter.builder import CommandBuilder
    from app.services.tools.adapter.parser import OutputParser

    logger.info("Executing tool %s against %s", tool_id, target)

    # Get tool from registry
    registry = get_registry()
    tool = registry.get_tool(tool_id)

    if not tool:
        return _error_result(tool_id, target, f"Tool not found: {tool_id}")

    # Auto-install if not available
    if not tool.is_available:
        logger.info("Tool %s not installed, attempting install...", tool_id)
        install_result = await install_tool_job(ctx, tool_id)
        if not install_result.get("success"):
            return _error_result(
                tool_id,
                target,
                f"Tool installation failed: {install_result.get('error', 'Unknown error')}",
            )
        # Refresh tool reference
        tool = registry.get_tool(tool_id)
        if not tool or not tool.is_available:
            return _error_result(
                tool_id, target, "Tool still not available after install"
            )

    # Setup output directory - use provided dir or create a temp one
    if not output_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = f"{tool_id}_{timestamp}_{uuid.uuid4().hex[:4]}"
        # Use /tmp for worker-initiated runs without a mission context
        output_dir = f"/tmp/spectra_tool_outputs/{run_id}"

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Build command
    config = tool.config
    builder = CommandBuilder(config)
    parser = OutputParser(config)

    request = ToolExecutionRequest(
        tool_id=tool_id,
        target=target,
        args=args or {},
        timeout=timeout,
    )

    try:
        command = builder.build_command(request, output_dir)
    except ValueError as e:
        return _error_result(tool_id, target, f"Command build failed: {e}")

    # Calculate timeout
    effective_timeout = timeout or config.execution.timeout
    if "/" in target:  # CIDR range
        try:
            network = ipaddress.ip_network(target, strict=False)
            host_count = min(network.num_addresses, MAX_HOSTS_DEFAULT)
            effective_timeout = max(
                effective_timeout, config.execution.timeout_per_host * host_count
            )
        except ValueError:
            logger.debug(
                "Target '%s' is not a valid IP network; skipping dynamic timeout adjustment",
                target,
            )

    effective_timeout = min(effective_timeout, config.execution.max_timeout)
    effective_timeout = max(effective_timeout, config.execution.min_timeout)

    # Execute command with timeout
    wrapped_cmd = f"timeout -k 10s {effective_timeout}s {command}"
    logger.info("Running: %s (timeout: %ds)", command, effective_timeout)

    start_time = time.time()
    returncode, stdout, stderr = await _run_command(wrapped_cmd, effective_timeout + 30)
    duration = time.time() - start_time

    # Check success based on configured exit codes
    success_codes = config.execution.success_exit_codes or [0]
    success = returncode in success_codes
    if returncode == 124:  # timeout exit code
        success = False
        stderr = (
            stderr or ""
        ) + f"\n[Spectra] Command timed out after {effective_timeout}s"

    # Parse output
    output_file = None
    if "{output_file}" in config.execution.args_template:
        output_file = str(Path(output_dir) / f"{tool_id}_output")

    parsed_findings = []
    if stdout or (output_file and Path(output_file).exists()):
        try:
            parsed_findings = await parser.parse_output(stdout, stderr, output_file)
        except Exception as e:
            logger.warning("Failed to parse output for %s: %s", tool_id, e)

    # Track job stats in Redis
    redis: ArqRedis | None = ctx.get("redis")
    if redis:
        await _track_tool_stats(redis, tool_id, success, duration)

    return ToolExecutionResult(
        tool_id=tool_id,
        target=target,
        success=success,
        exit_code=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        output_file=output_file,
        parsed_findings=parsed_findings,
    ).model_dump()


# =============================================================================
# Tool Installation Jobs
# =============================================================================


async def install_tool_job(
    ctx: dict[str, Any],
    tool_id: str,
) -> dict[str, Any]:
    """
    Install a tool in the tools container.

    Args:
        ctx: ARQ context with redis connection.
        tool_id: ID of the tool to install.

    Returns:
        Dict with success status and details.
    """
    from app.services.tools.installer import ToolInstaller

    logger.info("Installing tool: %s", tool_id)
    installer = ToolInstaller()
    result = await installer.install(tool_id)

    # Sync status to Redis
    redis: ArqRedis | None = ctx.get("redis")
    if redis:
        await _sync_tool_status(redis, tool_id, result)

    return result


async def uninstall_tool_job(
    ctx: dict[str, Any],
    tool_id: str,
) -> dict[str, Any]:
    """
    Uninstall a tool from the tools container.

    Args:
        ctx: ARQ context with redis connection.
        tool_id: ID of the tool to uninstall.

    Returns:
        Dict with success status.
    """
    from app.services.tools.installer import ToolInstaller

    logger.info("Uninstalling tool: %s", tool_id)
    installer = ToolInstaller()
    result = await installer.uninstall(tool_id)

    # Sync status to Redis
    redis: ArqRedis | None = ctx.get("redis")
    if redis:
        await _sync_tool_status(
            redis,
            tool_id,
            {
                "success": result.get("success"),
                "status": "pending" if result.get("success") else "failed",
            },
        )

    return result


async def install_all_tools_job(
    ctx: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    """
    Install all registered tools that aren't already installed.

    Args:
        ctx: ARQ context.
        force: If True, reinstall even if already installed.

    Returns:
        Dict with installation results.
    """
    from app.services.tools.registry import get_registry

    registry = get_registry()
    tools = registry.list_tools()

    results = {"installed": [], "failed": [], "skipped": []}

    for tool in tools:
        tool_id = tool.config.id

        # Check if already installed
        if not force and _is_tool_installed(tool):
            results["skipped"].append(tool_id)
            continue

        # Install
        result = await install_tool_job(ctx, tool_id)
        if result.get("success"):
            results["installed"].append(tool_id)
        else:
            results["failed"].append(
                {"tool_id": tool_id, "error": result.get("error", "Unknown error")}
            )

    return results


# =============================================================================
# Plugin Management Jobs
# =============================================================================


async def reload_plugins_job(
    ctx: dict[str, Any],
    install_new: bool = True,
) -> dict[str, Any]:
    """
    Reload plugins from disk and optionally install new ones.

    Called when new plugins are uploaded via the web UI.

    Args:
        ctx: ARQ context.
        install_new: If True, automatically install newly discovered plugins.

    Returns:
        Dict with reload results.
    """
    from app.services.tools.registry import get_registry

    logger.info("Reloading plugins from disk...")
    registry = get_registry()

    # Get current tool IDs
    old_tool_ids = set(t.config.id for t in registry.list_tools())

    # Reload
    await registry.load_plugins()

    # Get new tool IDs
    new_tool_ids = set(t.config.id for t in registry.list_tools())
    added = new_tool_ids - old_tool_ids

    # Sync all statuses
    await sync_all_status_job(ctx)

    # Install new tools if requested
    installed = []
    if install_new and added:
        logger.info("Installing %d new plugins: %s", len(added), list(added))
        for tool_id in added:
            result = await install_tool_job(ctx, tool_id)
            if result.get("success"):
                installed.append(tool_id)

    return {
        "reloaded": len(new_tool_ids),
        "added": list(added),
        "installed": installed,
    }


# =============================================================================
# Status Sync Jobs
# =============================================================================


async def get_tool_status_job(
    ctx: dict[str, Any],
    tool_id: str,
) -> dict[str, Any]:
    """
    Get the current status of a tool.

    Args:
        ctx: ARQ context.
        tool_id: ID of the tool to check.

    Returns:
        Dict with tool status information.
    """
    from app.services.tools.registry import get_registry

    registry = get_registry()
    tool = registry.get_tool(tool_id)

    if not tool:
        return {"tool_id": tool_id, "found": False, "status": "unknown"}

    is_installed = _is_tool_installed(tool)

    return {
        "tool_id": tool_id,
        "found": True,
        "status": "ready" if is_installed else "pending",
        "is_installed": is_installed,
        "executable": _get_executable(tool),
    }


async def sync_all_status_job(
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """
    Sync status of all tools to Redis.

    Returns:
        Dict with count of tools synced.
    """
    from app.services.tools.registry import get_registry

    registry = get_registry()
    tools = registry.list_tools()
    redis: ArqRedis | None = ctx.get("redis")

    synced = 0
    for tool in tools:
        is_installed = _is_tool_installed(tool)
        tool.status = ToolStatus.READY if is_installed else ToolStatus.PENDING

        if redis:
            await _sync_tool_status(
                redis,
                tool.config.id,
                {
                    "status": tool.status.value,
                },
            )
        synced += 1

    return {"synced": synced, "total": len(tools)}


# =============================================================================
# Shell Command Execution Job (for arbitrary commands)
# =============================================================================


async def run_command_job(
    ctx: dict[str, Any],
    command: str,
    timeout: int = 300,
    cwd: str | None = None,
) -> dict[str, Any]:
    """
    Run an arbitrary shell command in the tools container.

    Used for custom scripts, one-off commands, etc.

    Args:
        ctx: ARQ context.
        command: Shell command to execute.
        timeout: Timeout in seconds.
        cwd: Working directory.

    Returns:
        Dict with exit code, stdout, stderr.
    """
    logger.info("Running command: %s", command[:100])

    wrapped = f"timeout -k 10s {timeout}s {command}"
    returncode, stdout, stderr = await _run_command(wrapped, timeout + 30, cwd)

    return {
        "success": returncode == 0,
        "exit_code": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


async def execute_script_job(
    ctx: dict[str, Any],
    content: str,
    language: str,
    target: str,
    args: list[str] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """
    Execute a custom script (Python/Go/Bash).

    Args:
        ctx: ARQ context.
        content: Script content.
        language: Language (python, go, bash).
        target: Target IP/Domain (passed as arg).
        args: Additional arguments.
        timeout: Timeout in seconds.

    Returns:
        Dict with execution result.
    """
    # Create temp file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"script_{timestamp}_{uuid.uuid4().hex[:4]}"
    work_dir = Path(f"/tmp/spectra_scripts/{run_id}")
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        if language.lower() in ("python", "python3"):
            script_path = work_dir / "exploit.py"
            script_path.write_text(content)
            cmd = f"python3 {script_path} {target}"

        elif language.lower() == "go":
            script_path = work_dir / "exploit.go"
            script_path.write_text(content)
            # Compile then run
            compile_cmd = f"go build -o {work_dir}/exploit {script_path}"
            r_code, r_out, r_err = await _run_command(compile_cmd, GO_COMPILE_TIMEOUT, str(work_dir))
            if r_code != 0:
                return {
                    "success": False,
                    "exit_code": r_code,
                    "stdout": r_out,
                    "stderr": f"Compilation failed: {r_err}",
                }
            cmd = f"{work_dir}/exploit {target}"

        elif language.lower() in ("bash", "sh"):
            script_path = work_dir / "exploit.sh"
            script_path.write_text(content)
            await _run_command(f"chmod +x {script_path}", 5)
            cmd = f"{script_path} {target}"

        else:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Unsupported language: {language}",
            }

        # Add extra args
        if args:
            cmd += " " + " ".join(args)

        logger.info(f"Executing custom script ({language}) against {target}")

        # Run
        wrapped = f"timeout -k 10s {timeout}s {cmd}"
        returncode, stdout, stderr = await _run_command(
            wrapped, timeout + 30, str(work_dir)
        )

        return {
            "success": returncode == 0,
            "exit_code": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
        }
    finally:
        # Cleanup
        try:
            shutil.rmtree(work_dir)
        except Exception:
            pass


# =============================================================================
# Helper Functions
# =============================================================================


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
    command: str,
    timeout: int,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run a shell command with timeout."""
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    # Ensure /opt/spectra_tools is in PATH
    env["PATH"] = f"/opt/spectra_tools:{env.get('PATH', '')}"

    try:
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
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        return (-1, "", f"Command timed out after {timeout}s")


async def _track_tool_stats(
    redis: ArqRedis,
    tool_id: str,
    success: bool,
    duration: float,
) -> None:
    """Track tool execution statistics in Redis."""
    key = f"spectra:tool_stats:{tool_id}"

    try:
        # Increment counters atomically
        if success:
            await redis.hincrby(key, "success_count", 1)  # type: ignore[arg-type]
        else:
            await redis.hincrby(key, "fail_count", 1)  # type: ignore[arg-type]

        await redis.hincrby(key, "total_count", 1)  # type: ignore[arg-type]
        await redis.hset(key, "last_run", datetime.now().isoformat())  # type: ignore[arg-type]
        await redis.hset(key, "last_duration", str(duration))  # type: ignore[arg-type]
        await redis.expire(key, 86400 * 7)  # 7 day TTL  # type: ignore[arg-type]
    except Exception as e:
        logger.warning("Failed to track tool stats for %s: %s", tool_id, e)


async def _sync_tool_status(
    redis: Any,
    tool_id: str,
    result: dict[str, Any],
) -> None:
    """Sync tool status to Postgres Cache."""
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
    )
    await redis.expire(key, 3600)  # type: ignore[arg-type] # 1 hour TTL


# =============================================================================
# Worker Lifecycle
# =============================================================================


async def startup(ctx: dict[str, Any]) -> None:
    """Worker startup hook."""
    logger.info("=" * 60)
    logger.info("Spectra ARQ Worker starting in tools container...")
    logger.info("=" * 60)

    # Initialize tool registry
    try:
        from app.services.tools.registry import initialize_registry

        registry = await initialize_registry(
            plugins_dir="plugins",
            public_key_path="keys/plugin_signing.pub",
            safe_mode=settings.PLUGIN_SAFE_MODE,
        )
        logger.info("Loaded %d tool plugins", len(registry.list_tools()))
    except Exception as e:
        logger.error("Failed to initialize registry: %s", e, exc_info=True)
        return

    # Sync initial status and auto-install tools
    await _auto_install_pending()


async def _auto_install_pending() -> None:
    """Auto-install pending tools on startup."""
    from app.services.tools.registry import get_registry

    registry = get_registry()
    tools = registry.list_tools()

    pending = []
    for tool in tools:
        is_installed = _is_tool_installed(tool)
        tool.status = ToolStatus.READY if is_installed else ToolStatus.PENDING

        # Sync initial status
        await _sync_tool_status(
            None,
            tool.config.id,
            {
                "status": tool.status.value,
            },
        )

        if not is_installed:
            pending.append(tool.config.id)
        else:
            logger.info("Tool %s already installed", tool.config.id)

    if pending:
        logger.info("Auto-installing %d tools: %s", len(pending), pending)
        for tool_id in pending:
            try:
                from app.services.tools.installer import ToolInstaller

                installer = ToolInstaller()
                result = await installer.install(tool_id)

                if result.get("success"):
                    logger.info("[OK] Installed %s", tool_id)
                else:
                    logger.warning(
                        "[FAIL] Failed to install %s: %s", tool_id, result.get("error")
                    )

                await _sync_tool_status(None, tool_id, result)
            except Exception as e:
                logger.error("Error installing %s: %s", tool_id, e)
                await _sync_tool_status(
                    None,
                    tool_id,
                    {
                        "status": "failed",
                        "error": str(e),
                    },
                )


async def shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown hook."""
    logger.info("Spectra ARQ Worker shutting down...")


# =============================================================================
# Worker Configuration
# =============================================================================


class WorkerSettings:
    """ARQ worker configuration."""

    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD.get_secret_value(),
        database=settings.REDIS_DB,
    )

    functions = [
        # Tool execution
        execute_tool_job,
        # Installation
        install_tool_job,
        uninstall_tool_job,
        install_all_tools_job,
        # Plugin management
        reload_plugins_job,
        # Status
        get_tool_status_job,
        sync_all_status_job,
        # Generic command
        run_command_job,
        execute_script_job,
    ]

    on_startup = startup
    on_shutdown = shutdown

    max_jobs = ARQ_MAX_JOBS
    job_timeout = ARQ_JOB_TIMEOUT
    keep_result = ARQ_KEEP_RESULT
    health_check_interval = ARQ_HEALTH_CHECK_INTERVAL
    queue_name = ARQ_QUEUE_NAME


# =============================================================================
# Utility for App Container
# =============================================================================


async def get_arq_pool() -> ArqRedis:
    """Get ARQ Redis pool for enqueuing jobs from app container."""
    return await create_pool(
        WorkerSettings.redis_settings,
        default_queue_name=WorkerSettings.queue_name,
    )


if __name__ == "__main__":
    from arq import run_worker

    run_worker(WorkerSettings)  # type: ignore[arg-type]
