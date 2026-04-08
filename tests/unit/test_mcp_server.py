"""Tests for the MCP server endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_mcp_initialize():
    """MCP initialize returns server info."""
    from app.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="initialize", id=1)
    result = await handle_mcp_request(req, api_key="test-key", session=AsyncMock())

    assert result.result["serverInfo"]["name"] == "spectra-mcp"
    assert result.result["protocolVersion"] == "2024-11-05"
    assert "tools" in result.result["capabilities"]


async def test_mcp_tools_list():
    """MCP tools/list returns available tools."""
    from app.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="tools/list", id=2)
    result = await handle_mcp_request(req, api_key="test-key", session=AsyncMock())

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
    from app.api.mcp import MCP_TOOLS

    for tool in MCP_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


async def test_mcp_unknown_method():
    """MCP returns error for unknown methods."""
    from app.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="unknown/method", id=3)
    result = await handle_mcp_request(req, api_key="test-key", session=AsyncMock())

    assert result.error is not None
    assert result.error["code"] == -32601
    assert "unknown/method" in result.error["message"]


async def test_mcp_notifications_initialized():
    """MCP notifications/initialized returns empty result."""
    from app.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(method="notifications/initialized", id=4)
    result = await handle_mcp_request(req, api_key="test-key", session=AsyncMock())

    assert result.result == {}
    assert result.error is None


async def test_mcp_tool_call_unknown_tool():
    """MCP tools/call with unknown tool returns error."""
    from app.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(
        method="tools/call",
        id=5,
        params={"name": "nonexistent_tool", "arguments": {}},
    )
    result = await handle_mcp_request(req, api_key="test-key", session=AsyncMock())

    assert result.error is not None
    assert result.error["code"] == -32603


async def test_mcp_tool_start_mission():
    """MCP start_mission tool delegates to MissionManager."""
    from app.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(
        method="tools/call",
        id=6,
        params={
            "name": "start_mission",
            "arguments": {"target": "192.168.1.1", "directive": "Scan for open ports"},
        },
    )

    mock_manager = AsyncMock()
    mock_manager.start_mission.return_value = "test-mission-id-123"
    mock_manager.get_mission.return_value = None

    with patch("app.services.mission.manager.MissionManager", return_value=mock_manager):
        result = await handle_mcp_request(req, api_key="test-key", session=AsyncMock())

    assert result.error is None
    assert result.result["isError"] is False
    import json

    content = json.loads(result.result["content"][0]["text"])
    assert content["mission_id"] == "test-mission-id-123"
    assert content["target"] == "192.168.1.1"


async def test_mcp_tool_start_mission_missing_fields():
    """MCP start_mission requires target and directive."""
    from app.api.mcp import MCPRequest, handle_mcp_request

    req = MCPRequest(
        method="tools/call",
        id=7,
        params={"name": "start_mission", "arguments": {"target": "192.168.1.1"}},
    )
    result = await handle_mcp_request(req, api_key="test-key", session=AsyncMock())

    assert result.error is not None
    assert result.error["code"] == -32603
    assert result.error["message"] == "Internal tool execution error"


async def test_mcp_request_model_defaults():
    """MCPRequest has correct defaults."""
    from app.api.mcp import MCPRequest

    req = MCPRequest(method="test")
    assert req.jsonrpc == "2.0"
    assert req.id is None
    assert req.params is None


async def test_mcp_response_model():
    """MCPResponse serializes correctly."""
    from app.api.mcp import MCPResponse

    resp = MCPResponse(id=1, result={"key": "value"})
    assert resp.jsonrpc == "2.0"
    assert resp.id == 1
    assert resp.result == {"key": "value"}
    assert resp.error is None


async def test_mcp_api_key_verification_missing():
    """verify_mcp_api_key rejects missing key."""
    from fastapi import HTTPException

    from app.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await verify_mcp_api_key(mock_request)
    assert exc_info.value.status_code == 401


async def test_mcp_api_key_verification_invalid():
    """verify_mcp_api_key rejects wrong key."""
    from fastapi import HTTPException

    from app.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {"X-API-Key": "wrong-key"}

    with patch("app.api.mcp.settings") as mock_settings:
        mock_settings.MCP_API_KEY = "correct-key"
        with pytest.raises(HTTPException) as exc_info:
            await verify_mcp_api_key(mock_request)
    assert exc_info.value.status_code == 401


async def test_mcp_api_key_verification_bearer():
    """verify_mcp_api_key accepts Bearer token."""
    from app.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {"Authorization": "Bearer correct-key"}

    with patch("app.api.mcp.settings") as mock_settings:
        mock_settings.MCP_API_KEY = "correct-key"
        result = await verify_mcp_api_key(mock_request)
    assert result == "correct-key"


async def test_mcp_api_key_verification_not_configured():
    """verify_mcp_api_key returns 503 when MCP not configured."""
    from fastapi import HTTPException

    from app.api.mcp import verify_mcp_api_key

    mock_request = AsyncMock()
    mock_request.headers = {"X-API-Key": "some-key"}

    with patch("app.api.mcp.settings") as mock_settings:
        mock_settings.MCP_API_KEY = ""
        with pytest.raises(HTTPException) as exc_info:
            await verify_mcp_api_key(mock_request)
    assert exc_info.value.status_code == 503
