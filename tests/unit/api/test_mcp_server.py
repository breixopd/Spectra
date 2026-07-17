"""Tests for the MCP server endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _mock_http_request():
    """Create a mock Starlette Request for rate-limiter compatibility."""
    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.url.path = "/api/mcp"
    req.state = MagicMock()
    req.headers = {}
    return req


async def test_mcp_initialize():
    """MCP initialize returns server info."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="initialize", id=1)
    result = await handle_mcp_request(_mock_http_request(), body=req, api_key="test-key", session=AsyncMock())

    assert result.result["serverInfo"]["name"] == "spectra-mcp"
    assert result.result["protocolVersion"] == "2024-11-05"
    assert "tools" in result.result["capabilities"]


async def test_mcp_tools_list():
    """MCP tools/list returns available tools."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="tools/list", id=2)
    result = await handle_mcp_request(_mock_http_request(), body=req, api_key="test-key", session=AsyncMock())

    tools = result.result["tools"]
    assert len(tools) == 6
    tool_names = [t["name"] for t in tools]
    assert "start_mission" in tool_names
    assert "get_mission_status" in tool_names
    assert "get_findings" in tool_names
    assert "list_targets" in tool_names
    assert "search_knowledge_base" in tool_names
    assert "list_tools" in tool_names


async def test_mcp_tools_have_input_schema():
    """Each MCP tool has a valid inputSchema."""
    from spectra_api.api.mcp import MCP_TOOLS

    for tool in MCP_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


async def test_mcp_unknown_method():
    """MCP returns error for unknown methods."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="unknown/method", id=3)
    result = await handle_mcp_request(_mock_http_request(), body=req, api_key="test-key", session=AsyncMock())

    assert result.error is not None
    assert result.error["code"] == -32601
    assert "unknown/method" in result.error["message"]


async def test_mcp_notifications_initialized():
    """MCP notifications/initialized returns empty result."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="notifications/initialized", id=4)
    result = await handle_mcp_request(_mock_http_request(), body=req, api_key="test-key", session=AsyncMock())

    assert result.result == {}
    assert result.error is None


async def test_mcp_tool_call_unknown_tool():
    """MCP tools/call with unknown tool returns error."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(
        method="tools/call",
        id=5,
        params={"name": "nonexistent_tool", "arguments": {}},
    )
    result = await handle_mcp_request(_mock_http_request(), body=req, api_key="test-key", session=AsyncMock())

    assert result.error is not None
    assert result.error["code"] == -32603


async def test_mcp_tool_start_mission():
    """MCP start_mission uses the canonical launch policy with a server-bound user."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(
        method="tools/call",
        id=6,
        params={
            "name": "start_mission",
            "arguments": {
                "target": "192.168.1.1",
                "directive": "Scan for open ports",
                "authorization_confirmed": True,
                "user_id": "ignored-client-id",
            },
        },
    )

    mock_session = AsyncMock()
    mock_user = MagicMock(is_active=True)
    mock_session.get.return_value = mock_user
    launched = MagicMock()
    launched.id = "test-mission-id-123"
    launched.status = "created"
    launched.target = "192.168.1.1"

    with patch(
        "spectra_api.api.routers.missions.core.launch_mission_for_user",
        new=AsyncMock(return_value=launched),
    ) as launch:
        with patch("spectra_api.api.mcp.settings") as mock_settings:
            mock_settings.MCP_USER_ID = "server-bound-user"
            mock_settings.MCP_API_KEY = "test-key"
            result = await handle_mcp_request(_mock_http_request(), body=req, api_key="test-key", session=mock_session)

    assert result.error is None
    assert result.result["isError"] is False
    import json

    content = json.loads(result.result["content"][0]["text"])
    assert content["mission_id"] == "test-mission-id-123"
    assert content["target"] == "192.168.1.1"
    # Verify user_id was overridden to server-side value
    mock_session.get.assert_called_once()
    call_args = mock_session.get.call_args
    assert call_args[0][1] == "server-bound-user"
    launch.assert_awaited_once()
    launch_request = launch.await_args.args[1]
    launch_user = launch.await_args.args[3]
    assert launch_request.authorization_confirmed is True
    assert launch_request.requires_approval is True
    assert launch_user is mock_user


async def test_mcp_tool_start_mission_missing_fields():
    """MCP start_mission requires target and directive."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(
        method="tools/call",
        id=7,
        params={"name": "start_mission", "arguments": {"target": "192.168.1.1"}},
    )
    with patch("spectra_api.api.mcp.settings") as mock_settings:
        mock_settings.MCP_USER_ID = "server-user"
        mock_settings.MCP_API_KEY = "test-key"
        result = await handle_mcp_request(_mock_http_request(), body=req, api_key="test-key", session=AsyncMock())

    assert result.error is not None
    assert result.error["code"] == -32603
    assert result.error["message"] == "Internal tool execution error"


async def test_mcp_tool_start_mission_requires_explicit_authorization_confirmation():
    """MCP cannot bypass the product's written-authorization confirmation gate."""
    from spectra_api.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(
        method="tools/call",
        id=8,
        params={
            "name": "start_mission",
            "arguments": {"target": "192.168.1.1", "directive": "Scan"},
        },
    )

    with (
        patch("spectra_api.api.mcp.settings") as mock_settings,
        patch(
            "spectra_api.api.routers.missions.core.launch_mission_for_user",
            new=AsyncMock(),
        ) as launch,
    ):
        mock_settings.MCP_USER_ID = "server-bound-user"
        mock_settings.MCP_API_KEY = "test-key"
        result = await handle_mcp_request(
            _mock_http_request(),
            body=req,
            api_key="test-key",
            session=AsyncMock(),
        )

    assert result.error is not None
    launch.assert_not_awaited()


async def test_mcp_knowledge_search_is_tenant_scoped():
    """MCP RAG retrieval always carries the configured user's tenant scope."""
    from spectra_api.api.mcp import _execute_mcp_tool

    gateway = MagicMock()
    gateway.rag_search = AsyncMock(return_value=[])

    with (
        patch("spectra_api.api.mcp.settings") as mock_settings,
        patch("spectra_ai_core.gateway.ai_gateway.get_ai_gateway", return_value=gateway),
    ):
        mock_settings.MCP_USER_ID = "tenant-user"
        result = await _execute_mcp_tool(
            "search_knowledge_base",
            {"query": "prior mission"},
            AsyncMock(),
            request=_mock_http_request(),
        )

    assert result["count"] == 0
    gateway.rag_search.assert_awaited_once_with(
        query="prior mission",
        top_k=5,
        user_id="tenant-user",
    )


async def test_mcp_request_model_defaults():
    """MCPRequest has correct defaults."""
    from spectra_api.api.mcp import MCPRequest

    req = MCPRequest(method="test")
    assert req.jsonrpc == "2.0"
    assert req.id is None
    assert req.params is None


async def test_mcp_response_model():
    """MCPResponse serializes correctly."""
    from spectra_api.api.mcp import MCPResponse

    resp = MCPResponse(id=1, result={"key": "value"})
    assert resp.jsonrpc == "2.0"
    assert resp.id == 1
    assert resp.result == {"key": "value"}
    assert resp.error is None


async def test_mcp_api_key_verification_missing():
    """verify_mcp_api_key rejects missing key."""
    from fastapi import HTTPException

    from spectra_api.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await verify_mcp_api_key(mock_request)
    assert exc_info.value.status_code == 401


async def test_mcp_api_key_verification_invalid():
    """verify_mcp_api_key rejects wrong key."""
    from fastapi import HTTPException

    from spectra_api.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {"X-API-Key": "wrong-key"}

    with patch("spectra_api.api.mcp.settings") as mock_settings:
        mock_settings.MCP_API_KEY = "correct-key"
        with pytest.raises(HTTPException) as exc_info:
            await verify_mcp_api_key(mock_request)
    assert exc_info.value.status_code == 401


async def test_mcp_api_key_verification_bearer():
    """verify_mcp_api_key accepts Bearer token."""
    from spectra_api.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {"Authorization": "Bearer correct-key"}

    with patch("spectra_api.api.mcp.settings") as mock_settings:
        mock_settings.MCP_API_KEY = "correct-key"
        result = await verify_mcp_api_key(mock_request)
    assert result == "correct-key"


async def test_mcp_api_key_verification_not_configured():
    """verify_mcp_api_key returns 503 when MCP not configured."""
    from fastapi import HTTPException

    from spectra_api.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {"X-API-Key": "some-key"}

    with patch("spectra_api.api.mcp.settings") as mock_settings:
        mock_settings.MCP_API_KEY = ""
        with pytest.raises(HTTPException) as exc_info:
            await verify_mcp_api_key(mock_request)
    assert exc_info.value.status_code == 503
