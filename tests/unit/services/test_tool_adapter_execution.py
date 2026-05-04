from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_platform.services.tools.adapter import CommandToolAdapter
from spectra_tools_core.models import (
    ToolExecutionRequest,
)


@pytest.fixture
def mock_tool_config():
    config = MagicMock()
    config.id = "test-tool"
    config.execution.command = "nmap"
    config.execution.args_template = "-p {ports} {target}"
    config.execution.timeout = 10
    config.execution.timeout_per_host = 1
    config.execution.max_timeout = 60
    config.execution.min_timeout = 5
    config.execution.working_dir = "/tmp"
    config.execution.env = {}
    config.execution.success_exit_codes = [0]
    config.parsing.format = "text"
    config.parsing.mapping = {}
    config.parsing.capture_stderr = True
    config.parsing.combine_outputs = False
    return config


@pytest.fixture
def adapter(mock_tool_config):
    return CommandToolAdapter(mock_tool_config)


@pytest.mark.asyncio
async def test_execute_local_without_container_config(adapter):
    """Test execution runs locally (no docker exec wrapping)."""
    request = ToolExecutionRequest(tool_id="test-tool", target="127.0.0.1", args={"ports": "80"})

    with (
        patch("asyncio.create_subprocess_exec") as mock_subprocess,
    ):
        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"local stdout", b"")
        process_mock.returncode = 0
        mock_subprocess.return_value = process_mock

        result = await adapter.execute(request)

        assert result.success is True

        cmd_arg = mock_subprocess.call_args_list[0][0]
        # Should NOT use docker exec
        assert "docker exec" not in cmd_arg
        # Should still use timeout
        assert "timeout" in cmd_arg
        assert "-k" in cmd_arg
        # Should have base command
        assert "nmap" in cmd_arg
        assert "-p" in cmd_arg
        assert "80" in cmd_arg
        assert "127.0.0.1" in cmd_arg


@pytest.mark.asyncio
async def test_execute_command_locally(adapter):
    """Test executing a command locally (sandbox wrapping is handled externally)."""
    request = ToolExecutionRequest(tool_id="test-tool", target="127.0.0.1", args={"ports": "80"})

    with (
        patch("asyncio.create_subprocess_exec") as mock_subprocess,
    ):
        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"stdout output", b"")
        process_mock.returncode = 0
        mock_subprocess.return_value = process_mock

        result = await adapter.execute(request)

        assert result.success is True

        assert mock_subprocess.call_count >= 1

        cmd_arg = mock_subprocess.call_args_list[0][0]
        assert "docker exec" not in cmd_arg
        assert "timeout" in cmd_arg
        assert "nmap" in cmd_arg


@pytest.mark.asyncio
async def test_execute_timeout(adapter):
    """Test execution timeout handling."""
    request = ToolExecutionRequest(tool_id="test-tool", target="127.0.0.1", timeout=1)

    # Use built-in TimeoutError for side effect
    with (
        patch("asyncio.create_subprocess_exec") as mock_subprocess,
        patch("asyncio.wait_for", side_effect=TimeoutError),
        patch("os.killpg") as mock_kill,
        patch("os.getpgid"),
    ):
        process_mock = AsyncMock()
        process_mock.pid = 12345
        mock_subprocess.return_value = process_mock

        result = await adapter.execute(request)

        assert result.success is False
        assert "timed out" in result.stderr
        mock_kill.assert_called_once()


@pytest.mark.asyncio
async def test_output_file_handling(adapter):
    """Test logic for handling output files in command construction."""
    adapter.config.execution.args_template = "-oX {output_file} {target}"
    request = ToolExecutionRequest(tool_id="test-tool", target="127.0.0.1")
    output_dir = "/tmp/outputs"

    with (
        patch("asyncio.create_subprocess_exec") as mock_subprocess,
        patch("pathlib.Path.read_text", return_value="file content"),
        patch("pathlib.Path.read_bytes", return_value=b"file content"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=False),
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_stat.return_value.st_size = 100

        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"", b"")
        process_mock.returncode = 0
        mock_subprocess.return_value = process_mock

        result = await adapter.execute(request, output_dir=output_dir)

        assert result.success is True

        # We expect at least 1 call
        assert mock_subprocess.call_count >= 1

        # Check first call (execution)
        cmd_arg = mock_subprocess.call_args_list[0][0]
        assert "-oX" in cmd_arg
        assert f"{output_dir}/test-tool_output" in cmd_arg


@pytest.mark.asyncio
async def test_missing_target_error(adapter):
    """Test error when target is missing."""
    request = ToolExecutionRequest(tool_id="test-tool", target="")

    with pytest.raises(ValueError, match="target cannot be empty"):
        await adapter.execute(request)
