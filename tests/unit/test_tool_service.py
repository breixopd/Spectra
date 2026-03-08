"""Tests for ToolExecutionService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.tools.service import ToolExecutionService, StandaloneMissionAdapter
from app.services.tools.models import ToolExecutionResult
from app.services.ai.agents.base import ToolAction


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def tool_service(mock_llm):
    with patch("app.services.tools.service.SafetySupervisorAgent"), \
         patch("app.services.tools.service.VotingSystem"):
        svc = ToolExecutionService(mock_llm)
        yield svc


class TestStandaloneMissionAdapter:
    def test_creation(self):
        adapter = StandaloneMissionAdapter("10.0.0.1")
        assert adapter.target == "10.0.0.1"
        assert adapter.findings == []
        assert adapter.tool_runs == []

    def test_creation_with_job_id(self):
        adapter = StandaloneMissionAdapter("10.0.0.1", job_id="j1")
        assert adapter.id == "j1"

    def test_log(self):
        adapter = StandaloneMissionAdapter("10.0.0.1")
        adapter.log("test message")  # Should not raise

    def test_add_finding(self):
        adapter = StandaloneMissionAdapter("10.0.0.1")
        adapter.add_finding({"title": "SQLi", "severity": "high"})
        assert len(adapter.findings) == 1

    def test_record_tool_run(self):
        adapter = StandaloneMissionAdapter("10.0.0.1")
        adapter.record_tool_run("nmap")
        assert "nmap" in adapter.tool_runs


class TestToolExecutionServiceInit:
    def test_semaphore_limit(self, tool_service):
        assert tool_service._semaphore._value == 5

    def test_has_safety_supervisor(self, tool_service):
        assert tool_service.safety_supervisor is not None

    def test_has_consensus(self, tool_service):
        assert tool_service.consensus is not None


class TestToolServiceNormalization:
    def test_normalize_tool_name(self, tool_service):
        assert tool_service._normalize_tool_name("Nmap") == "nmap"
        assert tool_service._normalize_tool_name("NUCLEI") == "nuclei"
        assert tool_service._normalize_tool_name("sqlmap") == "sqlmap"


class TestToolServiceValidation:
    def test_validate_tool_name_valid(self, tool_service):
        assert tool_service._validate_tool_name("nmap")
        assert tool_service._validate_tool_name("nuclei-scanner")

    def test_validate_tool_name_invalid(self, tool_service):
        assert not tool_service._validate_tool_name("")
        assert not tool_service._validate_tool_name("rm -rf /")
        assert not tool_service._validate_tool_name("tool; cat /etc/passwd")
        assert not tool_service._validate_tool_name("A")  # uppercase


class TestToolServiceExecution:
    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self, tool_service):
        mission = MagicMock()
        mission.id = "m1"
        mission.log = MagicMock()

        with patch("app.services.tools.service.get_registry") as mock_reg:
            registry = mock_reg.return_value
            registry.sync_status_from_cache = AsyncMock()
            registry.get_tool = MagicMock(return_value=None)

            result = await tool_service.execute_request(
                mission=mission,
                tool_name="nonexistent_tool",
                target="10.0.0.1",
            )

        assert not result.success

    @pytest.mark.asyncio
    async def test_execute_custom_script(self, tool_service):
        mission = MagicMock()
        mission.id = "m1"
        mission.target = "10.0.0.1"
        mission.directive = "Test"
        mission.log = MagicMock()

        # Mock safety check to allow execution
        tool_service._perform_safety_check = AsyncMock(return_value=(True, "Safe"))

        with patch("app.core.queue.PostgresJobQueue") as MockQueue, \
             patch("app.core.queue.Job") as MockJob:
            mock_queue = MockQueue.return_value
            mock_queue.enqueue_job = AsyncMock(return_value="job-1")

            mock_job = MockJob.return_value
            mock_job.result = AsyncMock(return_value={
                "success": True,
                "stdout": "pwned",
                "stderr": "",
                "exit_code": 0,
            })

            result = await tool_service.execute_custom_script(
                mission=mission,
                script_content="print('hello')",
                language="python",
                target="10.0.0.1",
            )

        assert result.success
        assert result.stdout == "pwned"

    @pytest.mark.asyncio
    async def test_execute_custom_script_failure(self, tool_service):
        mission = MagicMock()
        mission.id = "m1"
        mission.target = "10.0.0.1"
        mission.directive = "Test"
        mission.log = MagicMock()

        tool_service._perform_safety_check = AsyncMock(return_value=(True, "Safe"))

        with patch("app.core.queue.PostgresJobQueue") as MockQueue, \
             patch("app.core.queue.Job") as MockJob:
            mock_queue = MockQueue.return_value
            mock_queue.enqueue_job = AsyncMock(return_value="job-1")

            mock_job = MockJob.return_value
            mock_job.result = AsyncMock(return_value=None)

            result = await tool_service.execute_custom_script(
                mission=mission,
                script_content="bad_code()",
                language="python",
                target="10.0.0.1",
            )

        assert not result.success

    @pytest.mark.asyncio
    async def test_execute_custom_script_exception(self, tool_service):
        mission = MagicMock()
        mission.id = "m1"
        mission.target = "10.0.0.1"
        mission.directive = "Test"
        mission.log = MagicMock()

        tool_service._perform_safety_check = AsyncMock(return_value=(True, "Safe"))

        with patch("app.core.queue.PostgresJobQueue", side_effect=Exception("queue fail")):
            result = await tool_service.execute_custom_script(
                mission=mission,
                script_content="code",
                language="python",
                target="10.0.0.1",
            )

        assert not result.success


class TestToolServiceErrorResult:
    def test_create_error_result(self, tool_service):
        result = tool_service._create_error_result("nmap", "10.0.0.1", "some error")
        assert isinstance(result, ToolExecutionResult)
        assert not result.success
        assert "some error" in result.stderr


class TestToolActionExecution:
    @pytest.mark.asyncio
    async def test_execute_tool_action(self, tool_service):
        mission = MagicMock()
        context = MagicMock()

        action = ToolAction(
            tool_name="nmap",
            target="10.0.0.1",
            tool_args={"ports": "1-1000"},
            risk_level="low",
            confidence=0.9,
            reasoning="Port scan",
        )

        mock_result = ToolExecutionResult(
            tool_id="nmap",
            target="10.0.0.1",
            success=True,
            exit_code=0,
            stdout="open ports found",
            stderr="",
            duration_seconds=5.0,
        )

        tool_service.execute_request = AsyncMock(return_value=mock_result)

        success = await tool_service.execute_tool_action(mission, action, context)
        assert success
