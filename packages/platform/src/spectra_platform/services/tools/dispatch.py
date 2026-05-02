"""Execution dispatch: build requests, dispatch to worker, process results."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from spectra_platform.services.ai.context import truncate_for_llm
from spectra_platform.services.tools.adapter import CommandToolAdapter
from spectra_platform.services.tools.execution import execute_via_worker
from spectra_platform.services.tools.output import (
    cleanup_output_directory,
    log_success,
    persist_output_directory,
    prepare_output_directory,
    update_attack_surface_from_finding,
)
from spectra_tools_core.models import RegisteredTool, ToolExecutionRequest, ToolExecutionResult

if TYPE_CHECKING:
    from spectra_platform.services.mission.mission import Mission
    from spectra_platform.services.mission.types import FindingDict

logger = logging.getLogger(__name__)


def build_execution_request(
    mission: Mission,
    tool: RegisteredTool,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    timeout: int | None,
) -> tuple[ToolExecutionRequest, CommandToolAdapter, str, str]:
    """Construct the execution request, adapter, command, and output dir."""
    configured_timeout = getattr(tool.config.execution, "timeout", 0)
    if not isinstance(configured_timeout, (int, float)):
        configured_timeout = 0

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_id = f"{tool_name}_{timestamp}_{uuid.uuid4().hex[:4]}"
    output_dir = prepare_output_directory(mission.id, run_id)

    effective_timeout = max(timeout or 0, int(configured_timeout))

    adapter = CommandToolAdapter(tool.config)
    request = ToolExecutionRequest(
        tool_id=tool_name,
        target=target,
        args=args or {},
        timeout=effective_timeout,
    )
    full_command = adapter.builder.build_command(request, output_dir=str(output_dir))

    args_str = ", ".join(f"{k}={v}" for k, v in (args or {}).items()) if args else "default"
    mission.log(f"[EXEC] Executing: {tool_name} | Target: {target} | Args: {args_str}")
    mission.log(f"[CMD] Command: {full_command[:200]}{'...' if len(full_command) > 200 else ''}")
    return request, adapter, full_command, str(output_dir)


async def dispatch_and_process_result(
    mission: Mission,
    tool: RegisteredTool,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    request: ToolExecutionRequest,
    adapter: CommandToolAdapter,
    full_command: str,
    output_dir: str,
    *,
    semaphore: asyncio.Semaphore,
    queue_name: str,
    default_timeout: int,
    buffer_timeout: int,
    max_stdout_chars: int,
    max_stderr_chars: int,
) -> ToolExecutionResult:
    """Apply stealth settings, dispatch to worker, and process the result."""
    try:
        stealth = tool.config.stealth
        if stealth and isinstance(getattr(stealth, "delay_ms", None), (int, float)) and stealth.delay_ms:
            delay_s = stealth.delay_ms / 1000.0
            mission.log(f"[STEALTH] Applying {stealth.delay_ms}ms delay before execution")
            await asyncio.sleep(delay_s)

        if stealth and getattr(stealth, "extra_args", None):
            full_command = adapter.builder.apply_stealth_args(full_command, stealth)

        async with semaphore:
            result = await execute_via_worker(
                tool_id=request.tool_id,
                target=request.target,
                args=request.args,
                timeout=request.timeout,
                output_dir=output_dir,
                mission_id=mission.id,
                queue_name=queue_name,
                default_timeout=default_timeout,
                buffer_timeout=buffer_timeout,
            )

        if result.success:
            result.stdout = truncate_for_llm(result.stdout, max_chars=max_stdout_chars, label="stdout")
            result.stderr = truncate_for_llm(result.stderr, max_chars=max_stderr_chars, label="stderr")
            log_success(mission, tool_name, result)
            for finding in result.parsed_findings:
                typed_finding = cast("FindingDict", finding)
                mission.add_finding(typed_finding)
                update_attack_surface_from_finding(mission, finding)
            mission.record_tool_run(
                tool_name,
                args=args,
                command=full_command,
                success=True,
            )
        else:
            last_error = result.stderr[:max_stderr_chars] if result.stderr else "No error message"
            mission.log(f"[ERROR] {tool_name} failed: {last_error[:200]}")
            mission.record_tool_run(
                tool_name,
                args=args,
                success=False,
                error=last_error,
            )

        return result
    finally:
        try:
            total_bytes = await persist_output_directory(mission.id, output_dir)
            if total_bytes > 0 and mission.user_id:
                from spectra_platform.services.billing.usage_tracker import UsageTracker

                await UsageTracker().record_storage_usage(mission.user_id, total_bytes)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("Failed to persist output directory %s: %s", output_dir, exc)
        cleanup_output_directory(output_dir)
