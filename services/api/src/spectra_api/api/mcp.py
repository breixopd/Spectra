"""
MCP (Model Context Protocol) Server for Spectra.

Exposes pentesting capabilities via the MCP JSON-RPC 2.0 protocol.
External AI agents (Claude, ChatGPT, Cursor) can use these tools to:
- Start pentesting missions
- Query findings and reports
- Search the RAG knowledge base
- List and manage targets

Authentication: API key via Bearer token or X-API-Key header.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_auth.rate_limit import RateLimits, limiter
from spectra_common.config import settings
from spectra_persistence.database import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["MCP"])


# --- MCP API Key Auth ---


async def verify_mcp_api_key(request: Request) -> str:
    """Verify MCP API key from header."""
    api_key = request.headers.get("X-API-Key") or ""
    if not api_key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth[7:]

    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    if not settings.MCP_API_KEY:
        raise HTTPException(status_code=503, detail="MCP server not configured")

    if not _constant_time_compare(api_key, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return api_key


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    import hmac

    return hmac.compare_digest(a.encode(), b.encode())


# --- MCP Protocol Models ---


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: Any = None
    error: dict[str, Any] | None = None


# --- MCP Tool Definitions ---

MCP_TOOLS = [
    {
        "name": "start_mission",
        "description": "Start a pentesting mission against a target. Returns the mission ID for tracking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target IP address, hostname, or CIDR range",
                },
                "directive": {
                    "type": "string",
                    "description": "What to look for. E.g., 'Perform a comprehensive vulnerability assessment'",
                },
                "user_id": {
                    "type": "string",
                    "description": "ID of the user initiating the mission",
                },
            },
            "required": ["target", "directive", "user_id"],
        },
    },
    {
        "name": "get_mission_status",
        "description": "Get the current status of a mission including findings count and phase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "UUID of the mission"},
                "user_id": {"type": "string", "description": "ID of the requesting user"},
            },
            "required": ["mission_id", "user_id"],
        },
    },
    {
        "name": "get_findings",
        "description": "Get findings from a mission. Returns vulnerability details.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "UUID of the mission"},
                "user_id": {"type": "string", "description": "ID of the requesting user"},
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "info"],
                    "description": "Filter by severity",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max findings to return (default 50)",
                    "default": 50,
                },
            },
            "required": ["mission_id", "user_id"],
        },
    },
    {
        "name": "list_targets",
        "description": "List all known targets from past missions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "ID of the requesting user"},
                "limit": {
                    "type": "integer",
                    "description": "Max targets to return (default 20)",
                    "default": 20,
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": "Search Spectra's RAG knowledge base for relevant security information, past findings, and tool documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_tools",
        "description": "List available security tools in Spectra.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# --- MCP Request Handler ---


@router.post("")
@router.post("/")
@limiter.limit(RateLimits.MCP)
async def handle_mcp_request(
    request: Request,
    body: MCPRequest,
    api_key: str = Depends(verify_mcp_api_key),
    session: AsyncSession = Depends(get_async_session),
) -> MCPResponse:
    """Handle MCP JSON-RPC 2.0 requests."""
    try:
        if body.method == "initialize":
            return MCPResponse(
                id=body.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "spectra-mcp",
                        "version": "1.0.0",
                    },
                },
            )

        elif body.method == "tools/list":
            return MCPResponse(id=body.id, result={"tools": MCP_TOOLS})

        elif body.method == "tools/call":
            params = body.params or {}
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            result = await _execute_mcp_tool(tool_name, arguments, session)
            return MCPResponse(
                id=body.id,
                result={
                    "content": [{"type": "text", "text": json.dumps(result)}],
                    "isError": False,
                },
            )

        elif body.method == "notifications/initialized":
            return MCPResponse(id=body.id, result={})

        else:
            return MCPResponse(
                id=body.id,
                error={"code": -32601, "message": f"Method not found: {body.method}"},
            )

    except HTTPException:
        raise
    except Exception:
        logger.exception("MCP tool execution failed: %s", body.method)
        return MCPResponse(
            id=body.id,
            error={"code": -32603, "message": "Internal tool execution error"},
        )


async def _execute_mcp_tool(tool_name: str, arguments: dict, session: AsyncSession) -> dict:
    """Execute an MCP tool and return results."""
    # Enforce server-side user scoping: override any user-supplied user_id
    # with the configured MCP_USER_ID to prevent impersonation.
    _USER_SCOPED_TOOLS = {"start_mission", "get_mission_status", "get_findings", "list_targets"}
    if tool_name in _USER_SCOPED_TOOLS:
        if not settings.MCP_USER_ID:
            raise ValueError("MCP_USER_ID is not configured; user-scoped operations are unavailable")
        arguments = {**arguments, "user_id": settings.MCP_USER_ID}

    if tool_name == "start_mission":
        return await _tool_start_mission(arguments, session)

    elif tool_name == "get_mission_status":
        return await _tool_get_mission_status(arguments, session)

    elif tool_name == "get_findings":
        return await _tool_get_findings(arguments, session)

    elif tool_name == "list_targets":
        return await _tool_list_targets(arguments, session)

    elif tool_name == "search_knowledge_base":
        return await _tool_search_knowledge_base(arguments)

    elif tool_name == "list_tools":
        return _tool_list_tools()

    else:
        raise ValueError(f"Unknown tool: {tool_name}")


async def _tool_start_mission(arguments: dict, session: AsyncSession) -> dict:
    """Start a new pentesting mission."""
    from spectra_mission.manager import mission_manager
    from spectra_persistence.models.user import User

    target = arguments.get("target", "")
    directive = arguments.get("directive", "")
    user_id = arguments.get("user_id", "")

    if not target or not directive:
        raise ValueError("Both 'target' and 'directive' are required")
    if not user_id:
        raise ValueError("'user_id' is required")

    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise ValueError(f"Invalid or inactive user: {user_id}")

    mission_id = await mission_manager.start_mission(
        target=target,
        directive=directive,
        user_id=user_id,
    )

    return {
        "mission_id": mission_id,
        "status": "created",
        "target": target,
        "message": f"Mission started against {target}",
    }


async def _tool_get_mission_status(arguments: dict, session: AsyncSession) -> dict:
    """Get mission status from the database."""
    from spectra_persistence.models.mission import Mission

    mission_id = arguments.get("mission_id", "")
    user_id = arguments.get("user_id", "")
    if not mission_id:
        raise ValueError("'mission_id' is required")
    if not user_id:
        raise ValueError("'user_id' is required")

    mission = (await session.execute(
        select(Mission).where(Mission.id == mission_id, Mission.user_id == user_id)
    )).scalar_one_or_none()

    if not mission:
        raise ValueError(f"Mission {mission_id} not found")

    summary = mission.summary or {}
    return {
        "mission_id": str(mission.id),
        "status": mission.status,
        "target": mission.target,
        "directive": mission.directive,
        "log_count": len(mission.logs or []),
        "created_at": str(mission.created_at),
        "summary": {k: v for k, v in summary.items() if k in ("findings_count", "phase", "tools_run")},
    }


async def _tool_get_findings(arguments: dict, session: AsyncSession) -> dict:
    """Get findings from a mission's persisted summary."""
    from spectra_mission.output_model import get_mission_findings
    from spectra_persistence.models.mission import Mission

    mission_id = arguments.get("mission_id", "")
    user_id = arguments.get("user_id", "")
    if not mission_id:
        raise ValueError("'mission_id' is required")
    if not user_id:
        raise ValueError("'user_id' is required")

    severity_filter = arguments.get("severity")
    limit = min(arguments.get("limit", 50), 100)

    mission = (await session.execute(
        select(Mission).where(Mission.id == mission_id, Mission.user_id == user_id)
    )).scalar_one_or_none()

    if not mission:
        raise ValueError(f"Mission {mission_id} not found")

    findings = get_mission_findings(mission)
    if severity_filter:
        findings = [f for f in findings if f.get("severity", "").lower() == severity_filter.lower()]

    return {
        "mission_id": mission_id,
        "total": len(findings),
        "returned": min(len(findings), limit),
        "findings": findings[:limit],
    }


async def _tool_list_targets(arguments: dict, session: AsyncSession) -> dict:
    """List known targets."""
    from spectra_persistence.models.target import Target

    limit = min(arguments.get("limit", 20), 100)
    user_id = arguments.get("user_id", "")
    if not user_id:
        raise ValueError("'user_id' is required")

    targets = (await session.execute(
        select(Target).where(Target.user_id == user_id).order_by(Target.created_at.desc()).limit(limit)
    )).scalars().all()

    return {
        "count": len(targets),
        "targets": [
            {
                "id": str(t.id),
                "address": t.address,
                "description": t.description,
                "os": t.os,
            }
            for t in targets
        ],
    }


async def _tool_search_knowledge_base(arguments: dict) -> dict:
    """Search RAG knowledge base."""
    from spectra_ai_core.gateway.ai_gateway import get_ai_gateway

    query = arguments.get("query", "")
    limit = min(arguments.get("limit", 5), 20)

    if not query:
        raise ValueError("'query' is required")

    gateway = get_ai_gateway()
    results = await gateway.rag_search(query=query, top_k=limit)

    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "content": (r.get("content", "")[:500]),
                "score": r.get("score", 0),
                "doc_type": r.get("doc_type", ""),
            }
            for r in results
        ],
    }


def _tool_list_tools() -> dict:
    """List available security tools."""
    from spectra_tools_core.registry import ToolRegistry

    registry = ToolRegistry()
    tools = registry.list_tools()

    return {
        "count": len(tools),
        "tools": [
            {
                "id": t.config.id,
                "name": t.config.name,
                "description": t.config.description,
                "category": t.config.category,
                "available": t.is_available,
            }
            for t in tools
        ],
    }
