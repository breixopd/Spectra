"""Tests for app.services.tools.dispatch module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.dispatch import build_execution_request, dispatch_and_process_result
from app.services.tools.models import ToolExecutionRequest, ToolExecutionResult


def _make_tool(timeout: int = 300):
    """Create a minimal mock RegisteredTool."""
    tool = MagicMock()
    tool.config.execution.timeout = timeout
    tool.config.stealth = None
    return tool


def _make_mission(mission_id: str = "mission-001"):
    """Create a minimal mock Mission."""
    mission = MagicMock()
    mission.id = mission_id
    mission.log = MagicMock()
    mission.add_finding = MagicMock()
    mission.record_tool_run = MagicMock()
    return mission


class TestBuildExecutionRequest:
    @patch("app.services.tools.dispatch.prepare_output_directory", return_value="/tmp/output")
    def test_basic_request_construction(self, mock_prepare):
        mission = _make_mission()
        tool = _make_tool(timeout=600)
        adapter_instance = MagicMock()
        adapter_instance.builder.build_command.return_value = "nmap -sV 10.0.0.1"

        with patch("app.services.tools.dispatch.CommandToolAdapter", return_value=adapter_instance):
            request, _adapter, _command, output_dir = build_execution_request(
                mission=mission,
                tool=tool,
                tool_name="nmap",
                target="10.0.0.1",
                args={"flags": "-sV"},
                timeout=300,
            )

        assert isinstance(request, ToolExecutionRequest)
        assert request.tool_id == "nmap"
        assert request.target == "10.0.0.1"
        assert request.args == {"flags": "-sV"}
        assert request.timeout == 600  # max(300, 600)
        assert output_dir == "/tmp/output"
        mission.log.assert_called()

    @patch("app.services.tools.dispatch.prepare_output_directory", return_value="/tmp/out")
    def test_timeout_uses_max_of_provided_and_configured(self, mock_prepare):
        mission = _make_mission()
        tool = _make_tool(timeout=100)
        adapter_instance = MagicMock()
        adapter_instance.builder.build_command.return_value = "cmd"

        with patch("app.services.tools.dispatch.CommandToolAdapter", return_value=adapter_instance):
            request, _, _, _ = build_execution_request(
                mission=mission, tool=tool, tool_name="test", target="t", args=None, timeout=500
            )

        assert request.timeout == 500

    @patch("app.services.tools.dispatch.prepare_output_directory", return_value="/tmp/out")
    def test_none_timeout_uses_configured(self, mock_prepare):
        mission = _make_mission()
        tool = _make_tool(timeout=200)
        adapter_instance = MagicMock()
        adapter_instance.builder.build_command.return_value = "cmd"

        with patch("app.services.tools.dispatch.CommandToolAdapter", return_value=adapter_instance):
            request, _, _, _ = build_execution_request(
                mission=mission, tool=tool, tool_name="test", target="t", args=None, timeout=None
            )

        assert request.timeout == 200

    @patch("app.services.tools.dispatch.prepare_output_directory", return_value="/tmp/out")
    def test_none_args_defaults_to_empty(self, mock_prepare):
        mission = _make_mission()
        tool = _make_tool()
        adapter_instance = MagicMock()
        adapter_instance.builder.build_command.return_value = "cmd"

        with patch("app.services.tools.dispatch.CommandToolAdapter", return_value=adapter_instance):
            request, _, _, _ = build_execution_request(
                mission=mission, tool=tool, tool_name="test", target="t", args=None, timeout=None
            )

        assert request.args == {}

    @patch("app.services.tools.dispatch.prepare_output_directory", return_value="/tmp/out")
    def test_non_numeric_configured_timeout_treated_as_zero(self, mock_prepare):
        mission = _make_mission()
        tool = _make_tool()
        tool.config.execution.timeout = "invalid"
        adapter_instance = MagicMock()
        adapter_instance.builder.build_command.return_value = "cmd"

        with patch("app.services.tools.dispatch.CommandToolAdapter", return_value=adapter_instance):
            request, _, _, _ = build_execution_request(
                mission=mission, tool=tool, tool_name="test", target="t", args=None, timeout=120
            )

        assert request.timeout == 120

    @patch("app.services.tools.dispatch.prepare_output_directory", return_value="/tmp/out")
    def test_long_command_truncated_in_log(self, mock_prepare):
        mission = _make_mission()
        tool = _make_tool()
        long_cmd = "x" * 300
        adapter_instance = MagicMock()
        adapter_instance.builder.build_command.return_value = long_cmd

        with patch("app.services.tools.dispatch.CommandToolAdapter", return_value=adapter_instance):
            build_execution_request(
                mission=mission, tool=tool, tool_name="test", target="t", args=None, timeout=None
            )

        # The CMD log line should contain '...' for truncation
        cmd_log_calls = [c for c in mission.log.call_args_list if "[CMD]" in str(c)]
        assert len(cmd_log_calls) == 1
        assert "..." in str(cmd_log_calls[0])


class TestDispatchAndProcessResult:
    @pytest.mark.asyncio
    @patch("app.services.tools.dispatch.persist_output_directory", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.cleanup_output_directory")
    @patch("app.services.tools.dispatch.execute_via_worker", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.truncate_for_llm", side_effect=lambda s, **kw: s)
    @patch("app.services.tools.dispatch.log_success")
    @patch("app.services.tools.dispatch.update_attack_surface_from_finding")
    async def test_successful_dispatch(
        self, mock_update_surface, mock_log_success, mock_truncate, mock_execute, mock_cleanup, mock_persist
    ):
        mission = _make_mission()
        tool = _make_tool()
        request = ToolExecutionRequest(tool_id="nmap", target="10.0.0.1", args={}, timeout=300)
        adapter = MagicMock()

        mock_execute.return_value = ToolExecutionResult(
            tool_id="nmap",
            target="10.0.0.1",
            success=True,
            stdout="scan complete",
            stderr="",
            exit_code=0,
            duration_seconds=1.5,
            parsed_findings=[],
        )

        result = await dispatch_and_process_result(
            mission=mission,
            tool=tool,
            tool_name="nmap",
            target="10.0.0.1",
            args={},
            request=request,
            adapter=adapter,
            full_command="nmap -sV 10.0.0.1",
            output_dir="/tmp/out",
            semaphore=asyncio.Semaphore(1),
            queue_name="default",
            default_timeout=300,
            buffer_timeout=60,
            max_stdout_chars=10000,
            max_stderr_chars=5000,
        )

        assert result.success is True
        mission.record_tool_run.assert_called_once_with("nmap", args={}, command="nmap -sV 10.0.0.1", success=True)
        mock_log_success.assert_called_once()
        mock_persist.assert_awaited_once()
        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.tools.dispatch.persist_output_directory", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.cleanup_output_directory")
    @patch("app.services.tools.dispatch.execute_via_worker", new_callable=AsyncMock)
    async def test_failed_dispatch_records_error(self, mock_execute, mock_cleanup, mock_persist):
        mission = _make_mission()
        tool = _make_tool()
        request = ToolExecutionRequest(tool_id="nmap", target="10.0.0.1", args={}, timeout=300)
        adapter = MagicMock()

        mock_execute.return_value = ToolExecutionResult(
            tool_id="nmap",
            target="10.0.0.1",
            success=False,
            stdout="",
            stderr="Connection refused",
            exit_code=1,
            duration_seconds=0.3,
            parsed_findings=[],
        )

        result = await dispatch_and_process_result(
            mission=mission,
            tool=tool,
            tool_name="nmap",
            target="10.0.0.1",
            args={},
            request=request,
            adapter=adapter,
            full_command="nmap 10.0.0.1",
            output_dir="/tmp/out",
            semaphore=asyncio.Semaphore(1),
            queue_name="default",
            default_timeout=300,
            buffer_timeout=60,
            max_stdout_chars=10000,
            max_stderr_chars=5000,
        )

        assert result.success is False
        mission.record_tool_run.assert_called_once()
        call_kwargs = mission.record_tool_run.call_args
        assert call_kwargs[1]["success"] is False
        assert "Connection refused" in call_kwargs[1]["error"]

    @pytest.mark.asyncio
    @patch("app.services.tools.dispatch.persist_output_directory", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.cleanup_output_directory")
    @patch("app.services.tools.dispatch.execute_via_worker", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.truncate_for_llm", side_effect=lambda s, **kw: s)
    @patch("app.services.tools.dispatch.log_success")
    @patch("app.services.tools.dispatch.update_attack_surface_from_finding")
    async def test_findings_added_to_mission(
        self, mock_update_surface, mock_log_success, mock_truncate, mock_execute, mock_cleanup, mock_persist
    ):
        mission = _make_mission()
        tool = _make_tool()
        request = ToolExecutionRequest(tool_id="nuclei", target="10.0.0.1", args={}, timeout=300)
        adapter = MagicMock()
        finding = {"name": "XSS", "host": "10.0.0.1", "severity": "high"}

        mock_execute.return_value = ToolExecutionResult(
            tool_id="nuclei",
            target="10.0.0.1",
            success=True,
            stdout="found xss",
            stderr="",
            exit_code=0,
            duration_seconds=2.0,
            parsed_findings=[finding],
        )

        await dispatch_and_process_result(
            mission=mission,
            tool=tool,
            tool_name="nuclei",
            target="10.0.0.1",
            args={},
            request=request,
            adapter=adapter,
            full_command="nuclei -t xss 10.0.0.1",
            output_dir="/tmp/out",
            semaphore=asyncio.Semaphore(1),
            queue_name="default",
            default_timeout=300,
            buffer_timeout=60,
            max_stdout_chars=10000,
            max_stderr_chars=5000,
        )

        mission.add_finding.assert_called_once()
        mock_update_surface.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.tools.dispatch.persist_output_directory", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.cleanup_output_directory")
    @patch("app.services.tools.dispatch.execute_via_worker", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.truncate_for_llm", side_effect=lambda s, **kw: s)
    @patch("app.services.tools.dispatch.log_success")
    @patch("app.services.tools.dispatch.update_attack_surface_from_finding")
    async def test_stealth_delay_applied(
        self, mock_update_surface, mock_log_success, mock_truncate, mock_execute, mock_cleanup, mock_persist
    ):
        mission = _make_mission()
        tool = _make_tool()
        tool.config.stealth = MagicMock()
        tool.config.stealth.delay_ms = 10  # 10ms delay
        tool.config.stealth.extra_args = None
        request = ToolExecutionRequest(tool_id="nmap", target="10.0.0.1", args={}, timeout=300)
        adapter = MagicMock()

        mock_execute.return_value = ToolExecutionResult(
            tool_id="nmap", target="10.0.0.1", success=True, stdout="ok", stderr="", exit_code=0, duration_seconds=0.5, parsed_findings=[]
        )

        with patch("app.services.tools.dispatch.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await dispatch_and_process_result(
                mission=mission,
                tool=tool,
                tool_name="nmap",
                target="10.0.0.1",
                args={},
                request=request,
                adapter=adapter,
                full_command="nmap 10.0.0.1",
                output_dir="/tmp/out",
                semaphore=asyncio.Semaphore(1),
                queue_name="default",
                default_timeout=300,
                buffer_timeout=60,
                max_stdout_chars=10000,
                max_stderr_chars=5000,
            )

            mock_sleep.assert_awaited_once_with(0.01)

    @pytest.mark.asyncio
    @patch("app.services.tools.dispatch.persist_output_directory", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.cleanup_output_directory")
    @patch("app.services.tools.dispatch.execute_via_worker", new_callable=AsyncMock)
    @patch("app.services.tools.dispatch.truncate_for_llm", side_effect=lambda s, **kw: s)
    @patch("app.services.tools.dispatch.log_success")
    @patch("app.services.tools.dispatch.update_attack_surface_from_finding")
    async def test_persist_failure_does_not_propagate(
        self, mock_update_surface, mock_log_success, mock_truncate, mock_execute, mock_cleanup, mock_persist
    ):
        """persist_output_directory failure should be caught, not raise."""
        mission = _make_mission()
        tool = _make_tool()
        request = ToolExecutionRequest(tool_id="nmap", target="10.0.0.1", args={}, timeout=300)
        adapter = MagicMock()
        mock_persist.side_effect = OSError("disk full")

        mock_execute.return_value = ToolExecutionResult(
            tool_id="nmap", target="10.0.0.1", success=True, stdout="ok", stderr="", exit_code=0, duration_seconds=0.1, parsed_findings=[]
        )

        # Should not raise
        result = await dispatch_and_process_result(
            mission=mission,
            tool=tool,
            tool_name="nmap",
            target="10.0.0.1",
            args={},
            request=request,
            adapter=adapter,
            full_command="nmap 10.0.0.1",
            output_dir="/tmp/out",
            semaphore=asyncio.Semaphore(1),
            queue_name="default",
            default_timeout=300,
            buffer_timeout=60,
            max_stdout_chars=10000,
            max_stderr_chars=5000,
        )
        assert result.success is True
        mock_cleanup.assert_called_once()
