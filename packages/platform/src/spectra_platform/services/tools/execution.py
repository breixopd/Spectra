"""Tool execution via job queue worker and tool installation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from spectra_domain.jobs import WorkerJobName
from spectra_platform.services.tools.output import create_error_result
from spectra_tools_core.models import ToolExecutionResult

if TYPE_CHECKING:
    from spectra_platform.services.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _is_tool_not_found_error(result_data: dict[str, Any]) -> bool:
    """Check if the worker result indicates the tool binary was missing."""
    stderr = (result_data.get("stderr") or "").lower()
    return any(
        keyword in stderr
        for keyword in [
            "not found",
            "tool unavailable",
            "unavailable in verified worker",
            "binary not found",
            "auto-install of",
        ]
    )


async def find_alternative_tools(tool_id: str, max_results: int = 3) -> list[dict[str, str]]:
    """Find alternative tools in the same category with overlapping capabilities.

    Args:
        tool_id: The ID of the tool that is unavailable.
        max_results: Maximum number of alternatives to return.

    Returns:
        List of dicts with 'id', 'name', 'category', and 'capabilities'.
    """
    from spectra_platform.services.tools.registry import get_registry

    registry = get_registry()
    tool = registry.get_tool(tool_id)
    if not tool:
        return []

    category = tool.config.category
    capabilities = set(tool.config.metadata.capabilities)

    alternatives: list[dict[str, str]] = []
    for t in registry.list_tools():
        if t.config.id == tool_id:
            continue
        if t.config.category != category:
            continue
        t_caps = set(t.config.metadata.capabilities)
        if capabilities & t_caps:  # Share at least one capability
            alternatives.append(
                {
                    "id": t.config.id,
                    "name": t.config.name,
                    "category": t.config.category,
                    "capabilities": ", ".join(t.config.metadata.capabilities),
                }
            )
            if len(alternatives) >= max_results:
                break

    logger.info("Found %d alternative tools for %s (category=%s)", len(alternatives), tool_id, category)
    return alternatives


async def execute_via_worker(
    tool_id: str,
    target: str,
    args: dict[str, Any] | None,
    timeout: int | None,
    output_dir: str,
    mission_id: str,
    queue_name: str,
    default_timeout: int,
    buffer_timeout: int,
) -> ToolExecutionResult:
    """Execute tool via PostgreSQL job queue worker and wait for result."""
    import html

    from spectra_platform.infrastructure.queue import Job, PostgresJobQueue
    from spectra_platform.mission.core.optimizations import tool_cache

    # Check cache first
    cached = tool_cache.get(tool_id, target, args or {})
    if cached is not None:
        logger.info("Using cached result for %s against %s", tool_id, target)
        return cached

    queue = PostgresJobQueue(queue_name)
    logger.debug(
        "Routing job to queue '%s' (mission=%s)",
        queue_name,
        mission_id[:8] if mission_id else "none",
    )

    try:
        job_id = await queue.enqueue_job(
            WorkerJobName.EXECUTE_TOOL,
            tool_id=tool_id,
            target=target,
            args=args,
            timeout=timeout,
            output_dir=output_dir,
        )

        job_timeout = (timeout or default_timeout) + buffer_timeout
        job = Job(job_id)
        result_data = await job.result(timeout=job_timeout)

        if result_data is None:
            return create_error_result(tool_id, target, "Job returned no result")

        # If the worker reported a missing-tool error, include alternative
        # tool suggestions in the error message for the caller.
        if not result_data.get("success") and _is_tool_not_found_error(result_data):
            stderr_hint = (result_data.get("stderr") or "")[:200]
            alternatives = await find_alternative_tools(tool_id)
            alt_hint = ""
            if alternatives:
                alt_names = [a["name"] for a in alternatives]
                alt_hint = f". Consider alternatives: {', '.join(alt_names)}"
            enhanced_error = f"{stderr_hint}{alt_hint}"
            logger.warning("Tool %s unavailable%s", tool_id, alt_hint)
            result_data["stderr"] = enhanced_error

        # OOM escalation: recreate sandbox at next tier and retry
        if isinstance(result_data, dict) and result_data.get("oom") and mission_id:
            from spectra_platform.services.tools.sandbox.escalation import attempt_oom_escalation

            escalated, message = await attempt_oom_escalation(mission_id)
            if escalated:
                logger.warning(
                    "OOM escalation triggered for mission %s: %s",
                    mission_id[:8],
                    message,
                )
                return await execute_via_worker(
                    tool_id=tool_id,
                    target=target,
                    args=args,
                    timeout=timeout,
                    output_dir=output_dir,
                    mission_id=mission_id,
                    queue_name=queue_name,
                    default_timeout=default_timeout,
                    buffer_timeout=buffer_timeout,
                )
            else:
                logger.error(
                    "OOM escalation failed for mission %s: %s",
                    mission_id[:8],
                    message,
                )

        result = ToolExecutionResult(**result_data)
        # Sanitize output for safe UI display
        result.stdout = html.escape(result.stdout)
        result.stderr = html.escape(result.stderr)
        if result.success:
            tool_cache.set(tool_id, target, args or {}, result)
        return result

    except TimeoutError:
        return create_error_result(tool_id, target, f"Job timed out after {job_timeout}s")
    except (OSError, RuntimeError, ValueError) as e:
        logger.error("Worker execution failed: %s", e)
        return create_error_result(tool_id, target, f"Worker error: {e}")


async def ensure_tool_installed(tool_id: str, install_timeout: int = 600) -> bool:
    """Queue and wait for a tool to be installed via the worker.

    Triggers the worker's auto-install flow by enqueuing an INSTALL_TOOL
    job, then waits for completion.  This is used pre-emptively by the
    validation layer before execution.

    Args:
        tool_id: The tool/plugin ID to install.
        install_timeout: Maximum seconds to wait for installation.

    Returns:
        True if the tool was installed successfully.
    """
    from spectra_platform.core.config import settings
    from spectra_platform.infrastructure.queue import Job, PostgresJobQueue

    queue = PostgresJobQueue(settings.TOOL_QUEUE_NAME)

    try:
        job_id = await queue.enqueue_job(WorkerJobName.INSTALL_TOOL, tool_id=tool_id)
        job = Job(job_id)

        result = await job.result(timeout=install_timeout)

        if result and result.get("status") == "success":
            from spectra_platform.services.tools.registry import get_registry
            from spectra_tools_core.models import ToolStatus

            registry = get_registry()
            tool = registry.get_tool(tool_id)
            if tool:
                tool.status = ToolStatus.PENDING
            return True

        # Check if worker side did an auto-install (golden image rebuild)
        from spectra_platform.services.tools.registry import get_registry
        from spectra_worker.helpers import _is_tool_installed

        registry = get_registry()
        tool = registry.get_tool(tool_id)
        if tool and _is_tool_installed(tool):
            logger.info("Tool %s was auto-installed by worker", tool_id)
            return True

        return False

    except (OSError, RuntimeError, ValueError) as e:
        logger.error("Tool installation failed for %s: %s", tool_id, e)
        return False
