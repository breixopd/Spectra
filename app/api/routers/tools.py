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
from pathlib import Path

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
)

from app.api.dependencies import get_current_active_user, get_current_superuser
from app.api.schemas import (
    CommandInfoResponse,
    InstallToolResponse,
    PluginSaveResponse,
    PluginUploadResponse,
    TestExecutionResponse,
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
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.rate_limit import RateLimits, limiter
from app.core.rbac import Permission, require_permission
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
    PluginSignatureError,
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


async def _get_cached_status(tool_id: str) -> dict[str, str | list[str] | None]:
    from app.core.cache import get_cache

    cache = get_cache()
    if not cache:
        return {}

    try:
        payload = await cache.get(f"spectra:tool_status:{tool_id}")
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.debug("Tool status lookup failed for %s: %s", tool_id, e)
        return {}

    return payload if isinstance(payload, dict) else {}


def _cached_logs(payload: dict[str, str | list[str] | None]) -> list[str]:
    logs = payload.get("logs")
    if not isinstance(logs, list):
        return []
    return [str(item) for item in logs if isinstance(item, str)]


# --- Endpoints ---


@router.post("/validate", response_model=ValidationResponse)
async def validate_plugin_config(
    config: dict = Body(...),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """
    Validate a plugin configuration schema.
    Does NOT check signature (as this is for pre-signing validation).
    """
    try:
        # Temporarily disable safe mode to validate schema only
        # Or better, use pydantic validation directly
        ToolConfig.model_validate(config)

        tool_config = ToolConfig.model_validate(config)
        registry.validator._validate_commands(tool_config)

        return ValidationResponse(valid=True, message="Plugin configuration is valid")
    except ValueError as e:
        # Pydantic validation errors are safe to expose
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (TypeError, KeyError, AttributeError) as e:
        logger.warning("Plugin validation failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid plugin configuration") from e


@router.post("/sign")
async def sign_plugin_config(
    config: dict = Body(...),
    private_key_pem: str | None = Body(None, description="Optional PEM-encoded Ed25519 private key"),
    _current_user: User = Depends(get_current_superuser),
):
    """
    Sign a plugin configuration using server key or a provided private key.

    If private_key_pem is provided, uses that key (for official/dev signing).
    Otherwise, uses the server's private key (only in DEBUG mode).
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key: Ed25519PrivateKey | None = None

        if private_key_pem:
            # Use provided key (works in any mode)
            try:
                key_data = private_key_pem.encode("utf-8")
                loaded_key = serialization.load_pem_private_key(key_data, password=None)
                if not isinstance(loaded_key, Ed25519PrivateKey):
                    raise HTTPException(status_code=400, detail="Key must be Ed25519 type")
                private_key = loaded_key
            except HTTPException:
                raise
            except (ValueError, TypeError, OSError) as e:
                logger.warning("Private key parsing failed: %s", e)
                raise HTTPException(status_code=400, detail="Invalid private key format") from e
        else:
            # Use server key (DEBUG only)
            if not settings.DEBUG:
                raise HTTPException(
                    status_code=403,
                    detail="Server signing disabled in production. Provide your own key or sign offline.",
                )

            key_path = Path("keys/plugin_signing.pem")
            if not key_path.exists():
                raise HTTPException(status_code=503, detail="Signing key not available on server")

            with open(key_path, "rb") as f:
                loaded_key = serialization.load_pem_private_key(f.read(), password=None)

            if not isinstance(loaded_key, Ed25519PrivateKey):
                raise HTTPException(status_code=500, detail="Invalid server key type")
            private_key = loaded_key

        # Remove existing signature
        config.pop("signature", None)

        # Canonicalize
        canonical_json = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")

        # Sign
        if private_key is None:
            raise HTTPException(status_code=500, detail="Signing key not resolved")
        signature = private_key.sign(canonical_json)
        config["signature"] = signature.hex()

        return config

    except ImportError as e:
        raise HTTPException(status_code=500, detail="Cryptography package not available") from e
    except HTTPException:
        raise
    except (ValueError, TypeError, OSError) as e:
        logger.error("Plugin signing failed: %s", e)
        raise HTTPException(status_code=500, detail="Signing failed - check server logs") from e


@router.post("/save-unsigned", response_model=PluginSaveResponse)
async def save_plugin_unsigned(
    config: dict = Body(...),
    _current_user: User = Depends(get_current_superuser),
):
    """
    Save a plugin without signing.
    Will only work if safe_mode is disabled.
    """
    from app.services.tools.registry import get_registry

    registry = get_registry()
    if not registry:
        raise HTTPException(status_code=503, detail="Tool registry not available")

    if settings.PLUGIN_SAFE_MODE:
        raise HTTPException(
            status_code=403,
            detail="Cannot save unsigned plugins in safe mode. Disable safe_mode or sign the plugin.",
        )

    try:
        # Remove any signature field
        config.pop("signature", None)

        # Validate structure
        tool_config = registry.validate_plugin(config)

        # Save to file
        plugin_path = Path("plugins") / f"{tool_config.id}.json"
        with open(plugin_path, "w") as f:
            json.dump(config, f, indent=2)

        # Reload into registry
        await registry.load_plugins()

        return PluginSaveResponse(
            status="saved",
            tool_id=tool_config.id,
            message="Plugin saved without signature (safe_mode disabled)",
        )
    except (ValueError, TypeError, OSError) as e:
        logger.error("Failed to save unsigned plugin: %s", e)
        raise HTTPException(
            status_code=400, detail="Failed to save unsigned plugin due to validation or server error."
        ) from e


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
    # Sync tool status from cache (set by tools container worker)
    try:
        await registry.sync_status_from_cache()
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.debug("Tool status sync failed: %s", e)

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
    try:
        await registry.sync_status_from_cache()
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.debug("Tool status sync failed: %s", e)

    tool = registry.get_tool(tool_id)

    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")

    cached_status = await _get_cached_status(tool_id)

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
        execution_command=tool.config.execution.command,
        args_template=tool.config.execution.args_template,
        timeout=tool.config.execution.timeout,
        icon=tool.config.ui.icon,
        color=tool.config.ui.color,
        status_message=str(cached_status.get("message") or "") or None,
        status_phase=str(cached_status.get("phase") or "") or None,
        last_updated=str(cached_status.get("last_updated") or "") or None,
        install_logs=_cached_logs(cached_status),
        last_output=str(cached_status.get("last_output") or "") or None,
    )


@router.get("/{tool_id}/config")
async def get_tool_execution_config(
    tool_id: str,
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
):
    """Get full execution configuration for building a manual execution form."""
    tool = registry.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")

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


@router.post("/upload", response_model=PluginUploadResponse)
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
    If safe_mode is enabled, the plugin must be signed.
    After upload, the tool will be installed in the background via the tools container.
    """
    # Validate file type
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="File must be a JSON file")

    if file.content_type != "application/json":
        raise HTTPException(status_code=400, detail="Invalid Content-Type. Must be application/json")

    # Read and parse (with size limit)
    MAX_PLUGIN_SIZE = 5 * 1024 * 1024  # 5MB
    try:
        content = await file.read(MAX_PLUGIN_SIZE + 1)
        if len(content) > MAX_PLUGIN_SIZE:
            raise HTTPException(status_code=413, detail="Plugin file too large (max 5MB)")
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e

    # Add to registry
    try:
        tool = await registry.add_plugin(data)

        # Queue background installation in the tools container
        async def _trigger_install():
            try:
                from app.core.queue import PostgresJobQueue

                queue = PostgresJobQueue()
                await queue.enqueue_job("install_tool_job", tool_id=tool.config.id)
                logger.info("Queued background install for %s", tool.config.id)
            except (OSError, RuntimeError, ConnectionError) as e:
                logger.error("Failed to queue install for %s: %s", tool.config.id, e)

        background_tasks.add_task(_trigger_install)

        return PluginUploadResponse(
            success=True,
            tool_id=tool.config.id,
            message=f"Plugin '{tool.config.name}' uploaded successfully. Installation queued in background.",
        )
    except PluginSignatureError as e:
        raise HTTPException(status_code=403, detail=f"Signature verification failed: {e}") from e
    except PluginValidationError as e:
        raise HTTPException(status_code=400, detail=f"Plugin validation failed: {e}") from e


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

    async def _install():
        try:
            from app.core.queue import PostgresJobQueue

            queue = PostgresJobQueue()
            await queue.enqueue_job("install_all_tools_job", force=force)
            logger.info("Queued install_all_tools job")
        except (OSError, RuntimeError, ConnectionError) as e:
            logger.error("Failed to queue install_all_tools: %s", e)

    background_tasks.add_task(_install)

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.TOOL_INSTALLED,
            user_id=str(_current_user.id),
            details={"action": "install_all"},
            request=request,
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
    tool = registry.get_tool(tool_id)

    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")

    if tool.status == ToolStatus.READY:
        return InstallToolResponse(
            success=True,
            tool_id=tool_id,
            status=tool.status,
            message="Tool is already installed",
        )

    if tool.status == ToolStatus.INSTALLING:
        return InstallToolResponse(
            success=True,
            tool_id=tool_id,
            status=tool.status,
            message="Tool installation already in progress",
        )

    # Queue installation via job queue worker in tools container
    async def _install():
        try:
            from app.core.queue import PostgresJobQueue

            queue = PostgresJobQueue()
            await queue.enqueue_job("install_tool_job", tool_id=tool_id)
            logger.info("Queued install job for %s", tool_id)
        except (OSError, RuntimeError, ConnectionError) as e:
            logger.error("Failed to queue install for %s: %s", tool_id, e)

    background_tasks.add_task(_install)

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.TOOL_INSTALLED,
            user_id=str(_current_user.id),
            details={"tool_id": tool_id},
            request=request,
        )

    return InstallToolResponse(
        success=True,
        tool_id=tool_id,
        status=ToolStatus.INSTALLING,
        message="Installation queued in tools container",
    )


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
    tool = await registry.set_enabled(tool_id, True)

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.TOOL_ENABLED,
            user_id=str(_current_user.id),
            details={"tool_id": tool_id},
            request=request,
        )

    return InstallToolResponse(
        success=True,
        tool_id=tool_id,
        status=tool.status.value,
        message=f"Tool '{tool.config.name}' enabled",
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
    tool = await registry.set_enabled(tool_id, False)

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.TOOL_DISABLED,
            user_id=str(_current_user.id),
            details={"tool_id": tool_id},
            request=request,
        )

    return InstallToolResponse(
        success=True,
        tool_id=tool_id,
        status=tool.status.value,
        message=f"Tool '{tool.config.name}' disabled",
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

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.TOOL_REMOVED,
            user_id=str(_current_user.id),
            details={"tool_id": tool_id},
            request=request,
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
    tool = registry.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")

    try:
        from app.core.queue import Job, PostgresJobQueue

        queue = PostgresJobQueue()

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

        async with async_session_maker() as session:
            await audit_log_event(
                session,
                AuditEventType.TOOL_EXECUTED,
                user_id=str(_current_user.id),
                details={"tool_id": tool_id},
                request=request,
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

    except (OSError, RuntimeError, TimeoutError, ValueError) as e:
        logger.error("Tool test failed for %s: %s", tool_id, e)
        raise HTTPException(status_code=500, detail="Test execution failed due to an internal error.")


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
    from app.core.cache import get_cache

    tool = registry.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")

    cache = get_cache()
    if not cache:
        return ToolStatsResponse(tool_id=tool_id, error="Cache not available")

    try:
        key = f"spectra:tool_stats:{tool_id}"
        stats = await cache.get(key)
        status_payload = await _get_cached_status(tool_id)

        if not stats or not isinstance(stats, dict):
            return ToolStatsResponse(
                tool_id=tool_id,
                status=str(status_payload.get("status") or "") or None,
                status_message=str(status_payload.get("message") or "") or None,
                last_updated=str(status_payload.get("last_updated") or "") or None,
                install_logs=_cached_logs(status_payload),
                error=str(status_payload.get("error") or "") or None,
            )

        return ToolStatsResponse(
            tool_id=tool_id,
            total_count=int(stats.get("total_count", 0)),
            success_count=int(stats.get("success_count", 0)),
            fail_count=int(stats.get("fail_count", 0)),
            last_run=stats.get("last_run"),
            last_duration=float(stats["last_duration"]) if stats.get("last_duration") else None,
            status=str(status_payload.get("status") or "") or None,
            status_message=str(status_payload.get("message") or "") or None,
            last_updated=str(status_payload.get("last_updated") or "") or None,
            install_logs=_cached_logs(status_payload),
            error=str(status_payload.get("error") or "") or None,
        )
    except (OSError, RuntimeError, KeyError, ValueError) as e:
        logger.error("Failed to get stats for %s: %s", tool_id, e)
        return ToolStatsResponse(tool_id=tool_id, error="Failed to retrieve statistics due to an internal error.")
