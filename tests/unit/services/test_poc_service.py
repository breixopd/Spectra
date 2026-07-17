"""Tests for the POC service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_ai_core.agents.base import AgentContext, AgentResult
from spectra_contracts.poc import POCMetadata, POCRequest, POCResult
from spectra_mission.poc.service import POCService


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def poc_service(mock_llm):
    with (
        patch("spectra_mission.poc.service.POCDeveloperAgent"),
        patch("spectra_mission.poc.service.VotingSystem") as MockVoting,
        patch("spectra_mission.poc.service.ToolExecutionService") as MockToolSvc,
    ):
        svc = POCService(mock_llm)
        svc.consensus = MockVoting.return_value
        svc.tool_service = MockToolSvc.return_value
        yield svc


@pytest.fixture
def poc_request():
    return POCRequest(
        target="192.168.1.100",
        vulnerability={"name": "CVE-2021-44228", "type": "rce"},
        port=8080,
    )


@pytest.fixture
def agent_context():
    return AgentContext(
        mission_id="m-test",
        target="192.168.1.100",
        session_id="test-session",
        user_id="u-test",
        user_role="user",
        plan_features={"custom_poc_execution": True, "shell_access": True},
        phase="poc",
    )


class TestPOCModels:
    def test_poc_request_creation(self):
        req = POCRequest(
            target="10.0.0.1",
            vulnerability={"name": "SQLi", "type": "sqli"},
        )
        assert req.target == "10.0.0.1"
        assert req.protocol == "tcp"
        assert req.constraints == []

    def test_poc_result_success(self):
        result = POCResult(success=True, content="print('exploit')")
        assert result.success
        assert result.error is None

    def test_poc_result_failure(self):
        result = POCResult(success=False, error="Consensus rejected")
        assert not result.success
        assert result.content is None

    def test_poc_metadata(self):
        meta = POCMetadata(
            name="Custom-SQLi",
            target_service="mysql",
            language="python",
        )
        assert meta.author == "Spectra AI"
        assert meta.shell_type == "reverse_shell"


class TestPOCServiceGenerate:
    @pytest.mark.asyncio
    async def test_custom_poc_execution_denied_when_target_out_of_scope(self, poc_service, poc_request, agent_context):
        out_of_scope_context = agent_context.model_copy(update={"target": "10.0.0.5"})

        result = await poc_service.generate_and_execute_poc(out_of_scope_context, poc_request)

        assert not result.success
        assert "capability policy" in result.error
        assert "target" in result.error

    @pytest.mark.asyncio
    async def test_generate_success(self, poc_service, poc_request, agent_context):
        # Mock developer agent success
        mock_action = MagicMock()
        mock_action.code_content = "import socket; print('exploit')"
        mock_action.language = "python"
        mock_action.risk_assessment = "medium"

        poc_service.developer_agent = AsyncMock()
        poc_service.developer_agent.execute = AsyncMock(return_value=AgentResult(success=True, action=mock_action))

        # Mock consensus approval
        mock_vote = MagicMock()
        mock_vote.status = "approved"
        poc_service.consensus.validate_at_gate = AsyncMock(return_value=mock_vote)

        # Mock tool execution success
        mock_exec = MagicMock()
        mock_exec.success = True
        mock_exec.stdout = "pwned"
        mock_exec.stderr = ""
        poc_service.tool_service.execute_custom_script = AsyncMock(return_value=mock_exec)

        with (
            patch("spectra_mission.poc.service.shell_relay_client") as mock_relay,
            patch("spectra_mission.poc.service.MissionArtifactWorkspace") as mock_workspace,
        ):
            mock_relay.start_listener = AsyncMock(return_value=4444)
            mock_workspace.return_value.put_artifact = AsyncMock(
                return_value=MagicMock(
                    id="artifact-1", key="m-test/workspace/artifacts/a/poc.py", sha256="abc", kind="custom_poc"
                )
            )
            result = await poc_service.generate_and_execute_poc(agent_context, poc_request)

        assert result.success
        assert result.content == "import socket; print('exploit')"
        assert result.evidence["artifact_id"] == "artifact-1"

    @pytest.mark.asyncio
    async def test_generate_agent_failure(self, poc_service, poc_request, agent_context):
        poc_service.developer_agent = AsyncMock()
        poc_service.developer_agent.execute = AsyncMock(return_value=AgentResult(success=False, error="LLM timeout"))

        with patch("spectra_mission.poc.service.shell_relay_client") as mock_relay:
            mock_relay.start_listener = AsyncMock(return_value=4444)
            result = await poc_service.generate_and_execute_poc(agent_context, poc_request)

        assert not result.success
        assert "Agent failed" in result.error or "LLM timeout" in result.error

    @pytest.mark.asyncio
    async def test_consensus_rejection(self, poc_service, poc_request, agent_context):
        mock_action = MagicMock()
        mock_action.code_content = "dangerous code"
        mock_action.language = "python"
        mock_action.risk_assessment = "critical"

        poc_service.developer_agent = AsyncMock()
        poc_service.developer_agent.execute = AsyncMock(return_value=AgentResult(success=True, action=mock_action))

        mock_vote = MagicMock()
        mock_vote.status = "rejected"
        mock_vote.escalation_reason = "Too dangerous"
        poc_service.consensus.validate_at_gate = AsyncMock(return_value=mock_vote)

        with patch("spectra_mission.poc.service.shell_relay_client") as mock_relay:
            mock_relay.start_listener = AsyncMock(return_value=4444)
            result = await poc_service.generate_and_execute_poc(agent_context, poc_request)

        assert not result.success
        assert "rejected" in result.error.lower() or "Too dangerous" in result.error

    @pytest.mark.asyncio
    async def test_execution_failure_returns_code(self, poc_service, poc_request, agent_context):
        mock_action = MagicMock()
        mock_action.code_content = "bad_code()"
        mock_action.language = "python"
        mock_action.risk_assessment = "low"

        poc_service.developer_agent = AsyncMock()
        poc_service.developer_agent.execute = AsyncMock(return_value=AgentResult(success=True, action=mock_action))

        mock_vote = MagicMock()
        mock_vote.status = "approved"
        poc_service.consensus.validate_at_gate = AsyncMock(return_value=mock_vote)

        mock_exec = MagicMock()
        mock_exec.success = False
        mock_exec.stderr = "SyntaxError: invalid syntax"
        poc_service.tool_service.execute_custom_script = AsyncMock(return_value=mock_exec)

        with patch("spectra_mission.poc.service.shell_relay_client") as mock_relay:
            mock_relay.start_listener = AsyncMock(return_value=4444)
            result = await poc_service.generate_and_execute_poc(agent_context, poc_request)

        assert not result.success
        assert result.content == "bad_code()"  # Returns code for debug

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, poc_service, poc_request, agent_context):
        poc_service.developer_agent = AsyncMock()
        poc_service.developer_agent.execute = AsyncMock(side_effect=RuntimeError("Unexpected"))

        with patch("spectra_mission.poc.service.shell_relay_client") as mock_relay:
            mock_relay.start_listener = AsyncMock(return_value=4444)
            result = await poc_service.generate_and_execute_poc(agent_context, poc_request)

        assert not result.success
        assert "Unexpected" in result.error
