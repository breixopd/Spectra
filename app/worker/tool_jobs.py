"""Tool execution, installation, uninstallation, and status sync jobs."""

from __future__ import annotations

import ipaddress
import logging
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.constants import MAX_HOSTS_DEFAULT
from app.services.tools.models import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolStatus,
)

from .helpers import (
    _error_result,
    _get_executable,
    _is_tool_installed,
    _run_command,
    _sync_tool_status,
    _track_tool_stats,
    with_retry,
)

logger = logging.getLogger(__name__)


async def _ensure_available_tool(registry: Any, tool_id: str, target: str) -> tuple[Any | None, dict[str, Any] | None]:
    tool = registry.get_tool(tool_id)
    if not tool:
        return None, _error_result(tool_id, target, f"Tool not found: {tool_id}")

    if tool.is_available:
        return tool, None

    logger.info("Tool %s not installed, attempting install...", tool_id)
    install_result = await install_tool_job(tool_id)
    if not install_result.get("success"):
        return None, _error_result(
            tool_id,
            target,
            f"Tool installation failed: {install_result.get('error', 'Unknown error')}",
        )

    tool = registry.get_tool(tool_id)
    if not tool or not tool.is_available:
        return None, _error_result(tool_id, target, "Tool still not available after install")

    return tool, None


def _resolve_output_dir(tool_id: str, output_dir: str | None) -> str:
    if output_dir:
        return output_dir

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_id = f"{tool_id}_{timestamp}_{uuid.uuid4().hex[:4]}"
    return tempfile.mkdtemp(prefix=f"spectra_tool_outputs_{run_id}_")


def _estimate_timeout_multiplier(tool_id: str, args: dict[str, Any] | None) -> float:
    """Estimate timeout multiplier based on argument patterns (tool-agnostic)."""
    multiplier = 1.0
    if not args:
        return multiplier

    args_str = " ".join(str(v) for v in args.values()).lower()

    # Deep/comprehensive scan indicators
    deep_scan_flags = ["-sv", "-sc", "-a ", "--script", "-p-", "--all-ports", "--full"]
    if any(flag in args_str for flag in deep_scan_flags):
        multiplier *= 2.0

    # Large wordlist or dictionary indicators
    wordlist_flags = ["-w ", "--wordlist", "-U ", "--usernames", "-P ", "--passwords", "/usr/share/wordlists/"]
    if any(flag in args_str for flag in wordlist_flags):
        multiplier *= 1.5

    # Template/plugin-heavy indicators
    template_flags = ["-t ", "--templates", "--template-dir", "-dP"]
    if any(flag in args_str for flag in template_flags):
        multiplier *= 2.0

    return min(multiplier, 4.0)  # Cap at 4x


def _calculate_effective_timeout(
    target: str,
    requested_timeout: int | None,
    execution: Any,
    tool_id: str | None = None,
    args: dict[str, Any] | None = None,
) -> int:
    effective_timeout = requested_timeout or execution.timeout

    if "/" in target:
        try:
            network = ipaddress.ip_network(target, strict=False)
            host_count = min(network.num_addresses, MAX_HOSTS_DEFAULT)
            effective_timeout = max(effective_timeout, execution.timeout_per_host * host_count)
        except ValueError:
            logger.debug(
                "Target '%s' is not a valid IP network; skipping dynamic timeout adjustment",
                target,
            )

    # Apply tool/args-based multiplier
    if tool_id:
        multiplier = _estimate_timeout_multiplier(tool_id, args)
        if multiplier > 1.0:
            logger.info("Timeout multiplier %.1fx for %s (args-based)", multiplier, tool_id)
            effective_timeout = int(effective_timeout * multiplier)

    effective_timeout = min(effective_timeout, execution.max_timeout)
    return max(effective_timeout, execution.min_timeout)


def _resolve_output_file(tool_id: str, output_dir: str, args_template: str) -> str | None:
    if "{output_file}" not in args_template:
        return None
    return str(Path(output_dir) / f"{tool_id}_output")


def _status_sync_callback(tool_id: str):
    async def progress_callback(update: dict[str, Any]) -> None:
        await _sync_tool_status(tool_id, update)

    return progress_callback


@with_retry()
async def execute_tool_job(
    tool_id: str,
    target: str,
    args: dict[str, Any] | None = None,
    timeout: int | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Execute a security tool locally in the tools container."""
    from app.services.tools.adapter.builder import CommandBuilder
    from app.services.tools.adapter.parser import OutputParser
    from app.services.tools.registry import get_registry

    logger.info("Executing tool %s against %s", tool_id, target)

    registry = get_registry()
    tool, error_result = await _ensure_available_tool(registry, tool_id, target)
    if error_result is not None:
        return error_result

    output_dir = _resolve_output_dir(tool_id, output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
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

        effective_timeout = _calculate_effective_timeout(target, timeout, config.execution, tool_id, args)

        # Execute command with timeout
        import time

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
            stderr = (stderr or "") + f"\n[Spectra] Command timed out after {effective_timeout}s"

        output_file = _resolve_output_file(tool_id, output_dir, config.execution.args_template)

        parsed_findings = []
        if stdout or (output_file and Path(output_file).exists()):
            try:
                parsed_findings = await parser.parse_output(stdout, stderr, output_file)
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Failed to parse output for %s: %s", tool_id, e)

        # Track job stats in cache
        await _track_tool_stats(tool_id, success, duration)

        result = ToolExecutionResult(
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

        # Flag OOM kills so the app side can trigger tier escalation
        if returncode == 137:
            result["oom"] = True

        return result
    finally:
        # Clean up temp output directory to prevent disk exhaustion
        output_dir_path = Path(output_dir)
        if output_dir_path.exists() and str(output_dir_path).startswith(tempfile.gettempdir()):
            shutil.rmtree(output_dir_path, ignore_errors=True)


@with_retry()
async def install_tool_job(
    tool_id: str,
) -> dict[str, Any]:
    """Install a tool in the tools container."""
    from app.services.tools.installer import ToolInstaller

    logger.info("Installing tool: %s", tool_id)
    installer = ToolInstaller()

    result = await installer.install(tool_id, progress_callback=_status_sync_callback(tool_id))

    await _sync_tool_status(tool_id, result)
    return result


@with_retry()
async def uninstall_tool_job(
    tool_id: str,
) -> dict[str, Any]:
    """Uninstall a tool from the tools container."""
    from app.services.tools.installer import ToolInstaller

    logger.info("Uninstalling tool: %s", tool_id)
    installer = ToolInstaller()

    result = await installer.uninstall(tool_id, progress_callback=_status_sync_callback(tool_id))

    await _sync_tool_status(
        tool_id,
        {
            "success": result.get("success"),
            "status": "pending" if result.get("success") else "failed",
        },
    )
    return result


async def install_all_tools_job(
    force: bool = False,
) -> dict[str, Any]:
    """Install all registered tools that aren't already installed."""
    from app.services.tools.registry import get_registry

    registry = get_registry()
    tools = registry.list_tools()

    results: dict[str, Any] = {"installed": [], "failed": [], "skipped": []}

    for tool in tools:
        tool_id = tool.config.id

        if not force and _is_tool_installed(tool):
            results["skipped"].append(tool_id)
            continue

        result = await install_tool_job(tool_id)
        if result.get("success"):
            results["installed"].append(tool_id)
        else:
            results["failed"].append({"tool_id": tool_id, "error": result.get("error", "Unknown error")})

    return results


async def reload_plugins_job(
    install_new: bool = True,
) -> dict[str, Any]:
    """Reload plugins from disk and optionally install new ones."""
    from app.services.tools.registry import get_registry

    logger.info("Reloading plugins from disk...")
    registry = get_registry()

    old_tool_ids = {t.config.id for t in registry.list_tools()}
    await registry.load_plugins()
    new_tool_ids = {t.config.id for t in registry.list_tools()}
    added = new_tool_ids - old_tool_ids

    await sync_all_status_job()

    installed = []
    if install_new and added:
        logger.info("Installing %d new plugins: %s", len(added), list(added))
        for tool_id in added:
            result = await install_tool_job(tool_id)
            if result.get("success"):
                installed.append(tool_id)

    return {
        "reloaded": len(new_tool_ids),
        "added": list(added),
        "installed": installed,
    }


async def get_tool_status_job(
    tool_id: str,
) -> dict[str, Any]:
    """Get the current status of a tool."""
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


async def sync_all_status_job() -> dict[str, Any]:
    """Sync status of all tools to cache."""
    from app.services.tools.registry import get_registry

    registry = get_registry()
    tools = registry.list_tools()

    synced = 0
    for tool in tools:
        is_installed = _is_tool_installed(tool)
        tool.status = ToolStatus.READY if is_installed else ToolStatus.PENDING

        await _sync_tool_status(
            tool.config.id,
            {"status": tool.status.value},
        )
        synced += 1

    return {"synced": synced, "total": len(tools)}
