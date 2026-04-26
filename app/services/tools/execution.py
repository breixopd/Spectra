"""Tool execution via job queue worker and tool installation."""

from __future__ import annotations

import logging
from typing import Any

from app.services.tools.models import ToolExecutionResult
from app.services.tools.output import create_error_result

logger = logging.getLogger(__name__)


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

    from app.core.optimizations import tool_cache
    from app.core.queue import Job, PostgresJobQueue

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
            "execute_tool_job",
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

        # OOM escalation: recreate sandbox at next tier and retry
        if isinstance(result_data, dict) and result_data.get("oom") and mission_id:
            from app.services.tools.sandbox.escalation import attempt_oom_escalation

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


async def ensure_tool_installed(tool_id: str, install_timeout: int) -> bool:
    """Ensure a tool is installed via the worker."""
    from app.core.config import settings
    from app.core.queue import Job, PostgresJobQueue

    queue = PostgresJobQueue(settings.TOOL_QUEUE_NAME)

    try:
        job_id = await queue.enqueue_job("install_tool_job", tool_id=tool_id)
        job = Job(job_id)

        result = await job.result(timeout=install_timeout)

        if result and result.get("success"):
            from app.services.tools.models import ToolStatus
            from app.services.tools.registry import get_registry

            registry = get_registry()
            tool = registry.get_tool(tool_id)
            if tool:
                tool.status = ToolStatus.READY
            return True
        return False

    except (OSError, RuntimeError, ValueError) as e:
        logger.error("Tool installation failed: %s", e)
        return False
