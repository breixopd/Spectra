"""
Tool Management API Router.

Provides endpoints for:
- Listing available tools
- Uploading new tool plugins
- Installing tools
- Getting tool status
"""

import json
import logging
import re

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.api.dependencies import get_current_active_user, get_current_superuser
from app.api.schemas import (
    CommandInfoResponse,
    InstallToolResponse,
    PluginUploadResponse,
    TestExecutionResponse,
    ToolAdminResponse,
    ToolDetailResponse,
    ToolExecConfigResponse,
    ToolListResponse,
    ToolMetadataResponse,
    ToolQueueResponse,
    ToolRemoveResponse,
    ToolStatsResponse,
    ToolStealthResponse,
    ToolSummary,
    ToolUIResponse,
    ValidationResponse,
)
from app.auth.rate_limit import RateLimits, limiter
from app.auth.rbac import Permission, require_permission
from app.core.config import settings
from app.core.database import async_session_maker
from app.infrastructure.events import EventType, events
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event
from app.services.tools.models import (
    RegisteredTool,
    ToolCategory,
    ToolConfig,
    ToolStatus,
)
from app.services.tools.registry import (
    PluginValidationError,
    ToolRegistry,
    get_registry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["Tools"])


# --- Dependency ---


def get_tool_registry() -> ToolRegistry:
    """Dependency to get the tool registry."""
    return get_registry()


def _to_summary(t: RegisteredTool) -> ToolSummary:
    """Convert a RegisteredTool to a ToolSummary."""
    return ToolSummary(
        id=t.config.id,
        name=t.config.name,
        version=t.config.version,
        category=t.config.category,
        description=t.config.description,
        status=t.status,
        enabled=t.config.enabled,
        icon=t.config.ui.icon,
        color=t.config.ui.color,
    )


def _validate_tool_config_schema(config: dict) -> ToolConfig:
    """Return a parsed tool config after schema validation succeeds."""
    return ToolConfig.model_validate(config)


async def _get_cached_status(tool_id: str) -> dict[str, str | list[str] | None]:
    """Read cached status data for a tool, ignoring cache transport failures."""
    from app.infrastructure.cache import get_cache

    cache = get_cache()
    if not cache:
        return {}

    try:
        payload = await cache.get(f"spectra:tool_status:{tool_id}")
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.warning("Tool status lookup failed for %s: %s", tool_id, e)
        return {}

    return payload if isinstance(payload, dict) else {}


def _cached_logs(payload: dict[str, str | list[str] | None]) -> list[str]:
    """Normalize cached log payloads to a plain string list."""
    logs = payload.get("logs")
    if not isinstance(logs, list):
        return []
    return [str(item) for item in logs if isinstance(item, str)]


def _cached_text(
    payload: dict[str, str | list[str] | None],
    key: str,
) -> str | None:
    """Return a cached scalar field as non-empty text."""
    return str(payload.get(key) or "") or None


def _tool_detail_status_fields(
    payload: dict[str, str | list[str] | None],
) -> dict[str, str | list[str] | None]:
    """Map cached status fields onto the tool detail response shape."""
    return {
        "status_message": _cached_text(payload, "message"),
        "status_phase": _cached_text(payload, "phase"),
        "last_updated": _cached_text(payload, "last_updated"),
        "install_logs": _cached_logs(payload),
        "last_output": _cached_text(payload, "last_output"),
    }


def _tool_stats_status_fields(
    payload: dict[str, str | list[str] | None],
) -> dict[str, str | list[str] | None]:
    """Map cached status fields onto the tool stats response shape."""
    return {
        "status": _cached_text(payload, "status"),
        "status_message": _cached_text(payload, "message"),
        "last_updated": _cached_text(payload, "last_updated"),
        "install_logs": _cached_logs(payload),
        "error": _cached_text(payload, "error"),
    }


async def _sync_registry_status_from_cache(registry: ToolRegistry) -> None:
    """Refresh in-memory tool status from cache when available."""
    try:
        await registry.sync_status_from_cache()
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.warning("Tool status sync failed: %s", e)


def _get_tool_or_404(registry: ToolRegistry, tool_id: str) -> RegisteredTool:
    tool = registry.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    return tool


def _queue_background_job(
    background_tasks: BackgroundTasks,
    job_name: str,
    *,
    success_log: str,
    failure_log: str,
    **job_kwargs,
) -> None:
    """Queue a worker job and log enqueue failures without failing the request."""

    async def _enqueue() -> None:
        try:
            from app.infrastructure.queue import PostgresJobQueue

            queue = PostgresJobQueue(settings.TOOL_QUEUE_NAME)
            await queue.enqueue_job(job_name, **job_kwargs)
            logger.info(success_log)
        except (OSError, RuntimeError, ConnectionError) as e:
            logger.error("%s: %s", failure_log, e)

    background_tasks.add_task(_enqueue)


def _build_install_response(
    tool_id: str,
    status: ToolStatus | str,
    message: str,
) -> InstallToolResponse:
    """Build the common response payload used by tool management routes."""
    return InstallToolResponse(
        success=True,
        tool_id=tool_id,
        status=status.value if isinstance(status, ToolStatus) else status,
        message=message,
    )


async def _write_tool_audit_event(
    event_type: AuditEventType,
    user_id: str,
    request: Request,
    details: dict[str, object],
) -> None:
    """Persist a tool-related audit record."""
    async with async_session_maker() as session:
        await audit_log_event(
            session,
            event_type,
            user_id=user_id,
            details=details,
            request=request,
        )


async def _queue_tool_job_with_audit(
    background_tasks: BackgroundTasks,
    job_name: str,
    *,
    success_log: str,
    failure_log: str,
    event_type: AuditEventType,
    user_id: str,
    request: Request,
    audit_details: dict[str, object],
    **job_kwargs,
) -> None:
    """Queue a background tool job and record the matching audit event."""
    _queue_background_job(
        background_tasks,
        job_name,
        success_log=success_log,
        failure_log=failure_log,
        **job_kwargs,
    )
    await _write_tool_audit_event(event_type, user_id, request, audit_details)


async def _set_tool_enabled(
    registry: ToolRegistry,
    tool_id: str,
    enabled: bool,
    event_type: AuditEventType,
    request: Request,
    current_user: User,
) -> InstallToolResponse:
    """Persist enabled state, audit the change, and shape the standard response."""
    tool = await registry.set_enabled(tool_id, enabled)
    await _write_tool_audit_event(
        event_type,
        str(current_user.id),
        request,
        {"tool_id": tool_id},
    )
    action = "enabled" if enabled else "disabled"
    await events.emit(EventType.PLUGIN_UPDATED, source="tools", tool_id=tool_id, action=action)
    return _build_install_response(tool_id, tool.status, f"Tool '{tool.config.name}' {action}")


# --- Endpoints ---


@router.post("/validate", response_model=ValidationResponse)
async def validate_plugin_config(
    config: dict = Body(...),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """
    Validate a plugin configuration schema.
    """
    try:
        tool_config = _validate_tool_config_schema(config)
        registry.validator._validate_commands(tool_config)

        return ValidationResponse(valid=True, message="Plugin configuration is valid")
    except ValueError as e:
        logger.warning("Plugin schema validation failed: %s", e)
        raise HTTPException(status_code=400, detail="Plugin configuration validation failed") from e
    except (TypeError, KeyError, AttributeError) as e:
        logger.warning("Plugin validation failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid plugin configuration") from e


@router.get(
    "",
    response_model=ToolListResponse,
    summary="List tools",
    description="Retrieve all registered security tools. Optionally filter by category or status.",
)
async def list_tools(
    category: ToolCategory | None = None,
    status: ToolStatus | None = None,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """
    List all registered tools.

    Optionally filter by category or status.
    """
    await _sync_registry_status_from_cache(registry)

    tools = registry.list_tools()

    # Apply filters
    if category:
        tools = [t for t in tools if t.config.category == category]
    if status:
        tools = [t for t in tools if t.status == status]

    summaries = [_to_summary(t) for t in tools]

    return ToolListResponse(tools=summaries, total=len(summaries))


@router.get("/available", response_model=ToolListResponse)
async def list_available_tools(
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """List only tools that are ready to use."""
    tools = registry.get_available_tools()

    summaries = [_to_summary(t) for t in tools]

    return ToolListResponse(tools=summaries, total=len(summaries))


@router.get("/{tool_id}", response_model=ToolDetailResponse)
async def get_tool(
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """Get detailed information about a specific tool."""
    await _sync_registry_status_from_cache(registry)
    tool = _get_tool_or_404(registry, tool_id)

    cached_status = await _get_cached_status(tool_id)
    status_fields = _tool_detail_status_fields(cached_status)

    return ToolDetailResponse(
        id=tool.config.id,
        name=tool.config.name,
        version=tool.config.version,
        category=tool.config.category,
        description=tool.config.description,
        status=tool.status,
        enabled=tool.config.enabled,
        installed_version=tool.installed_version,
        error_message=tool.error_message,
        timeout=tool.config.execution.timeout,
        icon=tool.config.ui.icon,
        color=tool.config.ui.color,
        **status_fields,
    )


@router.get("/{tool_id}/admin", response_model=ToolAdminResponse)
async def get_tool_admin(
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_superuser),
):
    """Get detailed information about a specific tool (admin-only).

    Includes sensitive execution metadata not exposed to regular users.
    """
    await _sync_registry_status_from_cache(registry)
    tool = _get_tool_or_404(registry, tool_id)

    cached_status = await _get_cached_status(tool_id)
    status_fields = _tool_detail_status_fields(cached_status)

    return ToolAdminResponse(
        id=tool.config.id,
        name=tool.config.name,
        version=tool.config.version,
        category=tool.config.category,
        description=tool.config.description,
        status=tool.status,
        enabled=tool.config.enabled,
        installed_version=tool.installed_version,
        error_message=tool.error_message,
        execution_command=tool.config.execution.command,
        args_template=tool.config.execution.args_template,
        timeout=tool.config.execution.timeout,
        icon=tool.config.ui.icon,
        color=tool.config.ui.color,
        **status_fields,
    )


@router.get("/{tool_id}/config")
async def get_tool_execution_config(
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """Get full execution configuration for building a manual execution form."""
    tool = _get_tool_or_404(registry, tool_id)

    config = tool.config

    placeholders = re.findall(r"\{(\w+)\}", config.execution.args_template)
    system_placeholders = {"output_file"}
    user_placeholders = [p for p in placeholders if p not in system_placeholders]

    return ToolExecConfigResponse(
        id=config.id,
        name=config.name,
        version=config.version,
        category=config.category,
        description=config.description,
        status=tool.status,
        command=config.execution.command,
        args_template=config.execution.args_template,
        timeout=config.execution.timeout,
        placeholders=user_placeholders,
        args_schema=config.execution.args_schema,
        arg_modifiers=config.execution.arg_modifiers,
        metadata=ToolMetadataResponse(
            ai_description=config.metadata.ai_description,
            capabilities=list(config.metadata.capabilities),
            risk_level=config.metadata.risk_level,
            tags=config.metadata.tags,
            supported_targets=list(config.metadata.supported_targets),
            use_cases=config.metadata.use_cases,
            limitations=config.metadata.limitations,
        ),
        stealth=ToolStealthResponse(
            rate_limit=config.stealth.rate_limit if config.stealth else None,
            delay_ms=config.stealth.delay_ms if config.stealth else None,
            extra_args=config.stealth.extra_args if config.stealth else {},
        ),
        parsing_format=config.parsing.format,
        ui=ToolUIResponse(icon=config.ui.icon, color=config.ui.color),
    )


@router.post("/upload", response_model=PluginUploadResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(RateLimits.TOOL_UPLOAD)
async def upload_plugin(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_superuser),
):
    """
    Upload a new tool plugin.

    The file should be a JSON configuration following the plugin schema.
    After upload, the tool will be installed in the background via the tools container.
    """
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="File must be a JSON file")

    if file.content_type != "application/json":
        raise HTTPException(status_code=400, detail="Invalid Content-Type. Must be application/json")

    MAX_PLUGIN_SIZE = 5 * 1024 * 1024
    try:
        content = await file.read(MAX_PLUGIN_SIZE + 1)
        if len(content) > MAX_PLUGIN_SIZE:
            raise HTTPException(status_code=413, detail="Plugin file too large (max 5MB)")
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.warning("Plugin upload JSON parse error: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON in plugin file") from e

    try:
        tool = await registry.add_plugin(data)
        _queue_background_job(
            background_tasks,
            "install_tool_job",
            success_log=f"Queued background install for {tool.config.id}",
            failure_log=f"Failed to queue install for {tool.config.id}",
            tool_id=tool.config.id,
        )

        await events.emit(EventType.PLUGIN_UPDATED, source="tools", tool_id=tool.config.id, action="uploaded")

        return PluginUploadResponse(
            success=True,
            tool_id=tool.config.id,
            message=f"Plugin '{tool.config.name}' uploaded successfully. Installation queued in background.",
        )
    except PluginValidationError as e:
        logger.warning("Plugin validation failed: %s", e)
        raise HTTPException(status_code=400, detail="Plugin validation failed") from e


@router.post("/install-all", response_model=ToolQueueResponse)
@limiter.limit(RateLimits.TOOL_INSTALL_ALL)
async def install_all_tools(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Reinstall even if already installed"),
    _current_user: User = Depends(get_current_superuser),
):
    """
    Queue installation of all tools via the tools container.

    This is useful for initial setup or reinstalling all tools.
    """
    await _queue_tool_job_with_audit(
        background_tasks,
        "install_all_tools_job",
        success_log="Queued install_all_tools job",
        failure_log="Failed to queue install_all_tools",
        event_type=AuditEventType.TOOL_INSTALLED,
        user_id=str(_current_user.id),
        request=request,
        audit_details={"action": "install_all"},
        force=force,
    )

    return ToolQueueResponse(
        success=True,
        message="Tool installation queued. Check /api/system/status for progress.",
    )


@router.post("/{tool_id}/install", response_model=InstallToolResponse)
@limiter.limit(RateLimits.TOOL_INSTALL)
async def install_tool(
    request: Request,
    response: Response,
    tool_id: str,
    background_tasks: BackgroundTasks,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_superuser),
):
    """
    Install a tool via the tools container worker.

    This queues the installation in the tools container and returns immediately.
    Check the tool's status via GET /tools/{tool_id} for progress.
    """
    tool = _get_tool_or_404(registry, tool_id)

    if tool.status == ToolStatus.INSTALLING:
        return _build_install_response(tool_id, tool.status, "Tool installation already in progress")

    await _queue_tool_job_with_audit(
        background_tasks,
        "install_tool_job",
        success_log=f"Queued install job for {tool_id}",
        failure_log=f"Failed to queue install for {tool_id}",
        event_type=AuditEventType.TOOL_INSTALLED,
        user_id=str(_current_user.id),
        request=request,
        audit_details={"tool_id": tool_id},
        tool_id=tool_id,
    )

    return _build_install_response(tool_id, ToolStatus.INSTALLING, "Installation queued in tools container")


@router.post("/{tool_id}/enable", response_model=InstallToolResponse)
@limiter.limit(RateLimits.TOOL_MANAGE)
async def enable_tool(
    request: Request,
    response: Response,
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_superuser),
):
    """Enable a plugin for platform use."""
    return await _set_tool_enabled(
        registry,
        tool_id,
        True,
        AuditEventType.TOOL_ENABLED,
        request,
        _current_user,
    )


@router.post("/{tool_id}/disable", response_model=InstallToolResponse)
@limiter.limit(RateLimits.TOOL_MANAGE)
async def disable_tool(
    request: Request,
    response: Response,
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_superuser),
):
    """Disable a plugin so it is hidden from platform execution paths."""
    return await _set_tool_enabled(
        registry,
        tool_id,
        False,
        AuditEventType.TOOL_DISABLED,
        request,
        _current_user,
    )


@router.delete("/{tool_id}", response_model=ToolRemoveResponse)
@limiter.limit(RateLimits.TOOL_REMOVE)
async def remove_tool(
    request: Request,
    response: Response,
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_superuser),
):
    """Remove a tool plugin from the registry."""
    success = await registry.remove_plugin(tool_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")

    await _write_tool_audit_event(
        AuditEventType.TOOL_REMOVED,
        str(_current_user.id),
        request,
        {"tool_id": tool_id},
    )

    return ToolRemoveResponse(success=True, message=f"Tool '{tool_id}' removed")


@router.get("/for-ai", response_model=list[dict])
async def get_tools_for_ai(
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """
    Get all available tools formatted for AI agents.

    Returns simplified tool information suitable for LLM prompts.
    """
    return registry.list_tools_for_ai()


@router.post("/{tool_id}/test", response_model=TestExecutionResponse)
@limiter.limit(RateLimits.TOOL_TEST)
async def test_tool(
    request: Request,
    response: Response,
    tool_id: str,
    target: str = Body(..., embed=True),
    args: dict | None = Body(None, embed=True),
    timeout: int | None = Body(None, embed=True),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = require_permission(Permission.USE_TOOLS),
):
    """
    Test a tool execution and return detailed output.

    Useful for debugging tool configuration and output parsing.
    Returns raw stdout/stderr, exit code, parsed findings, and execution details.
    """
    tool = _get_tool_or_404(registry, tool_id)

    try:
        from app.infrastructure.queue import Job, PostgresJobQueue

        queue = PostgresJobQueue(settings.TOOL_QUEUE_NAME)

        # Execute via job queue worker
        job_id = await queue.enqueue_job(
            "execute_tool_job",
            tool_id=tool_id,
            target=target,
            args=args or {},
            timeout=timeout or tool.config.execution.timeout,
            output_dir=None,  # let worker create one
        )

        # Wait for result with timeout
        job = Job(job_id)
        result = await job.result(timeout=timeout or 300)

        await _write_tool_audit_event(
            AuditEventType.TOOL_EXECUTED,
            str(_current_user.id),
            request,
            {"tool_id": tool_id},
        )

        # Return detailed result for debugging
        return TestExecutionResponse(
            tool_id=tool_id,
            target=target,
            success=result.get("success", False),
            exit_code=result.get("exit_code", -1),
            duration_seconds=result.get("duration_seconds", 0),
            stdout=result.get("stdout", "")[:5000],
            stderr=result.get("stderr", "")[:2000],
            output_file=result.get("output_file"),
            parsed_findings_count=len(result.get("parsed_findings", [])),
            parsed_findings=result.get("parsed_findings", [])[:20],
            command_info=CommandInfoResponse(
                base_command=tool.config.execution.command,
                args_template=tool.config.execution.args_template,
                timeout_used=timeout or tool.config.execution.timeout,
            ),
        )

    except (OSError, RuntimeError, TimeoutError, ValueError, Exception) as e:
        logger.error("Tool test failed for %s: %s", tool_id, e)
        raise HTTPException(status_code=500, detail=f"Test execution failed: {e}") from e


@router.get("/{tool_id}/stats")
async def get_tool_stats(
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """
    Get execution statistics for a tool.

    Returns success/failure counts, last run time, and average duration.
    """
    from app.infrastructure.cache import get_cache

    _get_tool_or_404(registry, tool_id)

    cache = get_cache()
    if not cache:
        return ToolStatsResponse(tool_id=tool_id, error="Cache not available")

    try:
        key = f"spectra:tool_stats:{tool_id}"
        stats = await cache.get(key)
        status_payload = await _get_cached_status(tool_id)
        status_fields = _tool_stats_status_fields(status_payload)

        if not stats or not isinstance(stats, dict):
            return ToolStatsResponse(tool_id=tool_id, **status_fields)

        return ToolStatsResponse(
            tool_id=tool_id,
            total_count=int(stats.get("total_count", 0)),
            success_count=int(stats.get("success_count", 0)),
            fail_count=int(stats.get("fail_count", 0)),
            last_run=stats.get("last_run"),
            last_duration=float(stats["last_duration"]) if stats.get("last_duration") else None,
            **status_fields,
        )
    except (OSError, RuntimeError, KeyError, ValueError) as e:
        logger.error("Failed to get stats for %s: %s", tool_id, e)
        return ToolStatsResponse(tool_id=tool_id, error="Failed to retrieve statistics due to an internal error.")
