import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.poc.service import POCService
from app.services.poc.models import POCRequest

@pytest.mark.asyncio
async def test_poc_lifecycle():
    """Test the full POC generation and execution flow."""
    mock_llm = AsyncMock()

    # Mock Agent Response
    mock_agent_result = MagicMock()
    mock_agent_result.success = True
    mock_agent_result.action = MagicMock()
    mock_agent_result.action.code_content = "print('pwned')"
    mock_agent_result.action.language = "python"
    mock_agent_result.action.risk_assessment = "Low"
    mock_agent_result.action.risk_level = "high"
    mock_agent_result.action.reasoning = "Test"

    # Mock LLM Agent execute
    mock_llm.generate_structured.return_value = mock_agent_result.action

    service = POCService(mock_llm)

    # Mock Consensus
    service.consensus.validate_at_gate = AsyncMock()
    service.consensus.validate_at_gate.return_value = MagicMock(status="approved")

    # Mock Tool Service
    service.tool_service.execute_custom_script = AsyncMock()
    service.tool_service.execute_custom_script.return_value = MagicMock(success=True)

    # Mock Agent Execute manually since we mocked LLM but Agent uses it
    service.developer_agent.execute = AsyncMock(return_value=mock_agent_result)

    # Mock Shell Manager (it's a global singleton, but we can patch start_listener)
    with pytest.MonkeyPatch.context() as m:
        m.setattr("app.services.shell.session_manager.shell_manager.start_listener", MagicMock())

        request = POCRequest(
            target="127.0.0.1",
            vulnerability={"name": "TestVuln"}
        )
        context = MagicMock()
        context.session_id = "test-session"

        result = await service.generate_and_execute_poc(context, request)

        assert result.success
        assert result.content == "print('pwned')"
        assert result.metadata.name == "Custom-TestVuln"
