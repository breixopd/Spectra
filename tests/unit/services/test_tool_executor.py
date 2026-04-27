"""Tests for the tool registry executor (command execution)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools.registry.executor import _read_stream_limit, run_command_safe


class TestRunCommandSafe:
    @pytest.mark.asyncio
    async def test_empty_command_returns_error(self):
        rc, _stdout, stderr = await run_command_safe("")
        assert rc == -1
        assert "Empty command" in stderr

    @pytest.mark.asyncio
    async def test_whitespace_command_returns_error(self):
        rc, _stdout, stderr = await run_command_safe("   ")
        assert rc == -1
        assert "Empty command" in stderr

    @pytest.mark.asyncio
    async def test_successful_command(self):
        rc, stdout, _stderr = await run_command_safe("echo hello")
        assert rc == 0
        assert "hello" in stdout

    @pytest.mark.asyncio
    async def test_failed_command_returns_nonzero(self):
        rc, _stdout, _stderr = await run_command_safe("false")
        assert rc != 0

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self):
        rc, _stdout, stderr = await run_command_safe("sleep 30", timeout=1)
        assert rc == -1
        assert "timed out" in stderr.lower()

    @pytest.mark.asyncio
    async def test_stderr_captured(self):
        _rc, _stdout, stderr = await run_command_safe("echo error >&2")
        assert "error" in stderr

    @pytest.mark.asyncio
    async def test_env_has_debian_frontend(self):
        _rc, stdout, _stderr = await run_command_safe("echo $DEBIAN_FRONTEND")
        assert "noninteractive" in stdout

    @pytest.mark.asyncio
    async def test_path_includes_spectra_tools(self):
        _rc, stdout, _stderr = await run_command_safe("echo $PATH")
        assert "/opt/spectra_tools" in stdout

    @pytest.mark.asyncio
    async def test_subprocess_creation_failure(self):
        with patch("asyncio.create_subprocess_shell", side_effect=OSError("spawn failed")):
            rc, _stdout, stderr = await run_command_safe("echo test")
            assert rc == -1
            assert "spawn failed" in stderr

    @pytest.mark.asyncio
    async def test_subprocess_exec_creation_failure(self):
        with patch("asyncio.create_subprocess_exec", side_effect=OSError("spawn failed")):
            rc, _stdout, stderr = await run_command_safe(["echo", "test"])
            assert rc == -1
            assert "spawn failed" in stderr

    @pytest.mark.asyncio
    async def test_stdout_and_stderr_both_captured(self):
        _rc, stdout, stderr = await run_command_safe("echo out && echo err >&2")
        assert "out" in stdout
        assert "err" in stderr

    @pytest.mark.asyncio
    async def test_exit_code_preserved(self):
        rc, _stdout, _stderr = await run_command_safe("exit 42")
        assert rc == 42

    @pytest.mark.asyncio
    async def test_missing_streams_returns_error(self):
        mock_proc = AsyncMock()
        mock_proc.stdout = None
        mock_proc.stderr = None
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            rc, _stdout, stderr = await run_command_safe("echo test")
            assert rc == -1
            assert "Failed to capture" in stderr

    @pytest.mark.asyncio
    async def test_missing_streams_exec_returns_error(self):
        mock_proc = AsyncMock()
        mock_proc.stdout = None
        mock_proc.stderr = None
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            rc, _stdout, stderr = await run_command_safe(["echo", "test"])
            assert rc == -1
            assert "Failed to capture" in stderr


class TestReadStreamLimit:
    @pytest.mark.asyncio
    async def test_reads_normal_content(self):
        reader = AsyncMock()
        reader.read = AsyncMock(side_effect=[b"hello world", b""])
        result = await _read_stream_limit(reader)
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        reader = AsyncMock()
        reader.read = AsyncMock(return_value=b"")
        result = await _read_stream_limit(reader)
        assert result == ""

    @pytest.mark.asyncio
    async def test_truncates_large_output(self):
        from app.services.tools.registry.constants import MAX_OUTPUT_SIZE

        # Simulate reading in 4096-byte chunks exceeding the limit
        chunk_count = (MAX_OUTPUT_SIZE // 4096) + 2
        chunks = [b"A" * 4096 for _ in range(chunk_count)] + [b""]
        reader = AsyncMock()
        reader.read = AsyncMock(side_effect=chunks)
        result = await _read_stream_limit(reader)
        assert "truncated" in result

    @pytest.mark.asyncio
    async def test_handles_utf8_errors(self):
        reader = AsyncMock()
        reader.read = AsyncMock(side_effect=[b"\xff\xfe invalid", b""])
        result = await _read_stream_limit(reader)
        assert isinstance(result, str)  # Should not raise

    @pytest.mark.asyncio
    async def test_multiple_chunks(self):
        reader = AsyncMock()
        reader.read = AsyncMock(side_effect=[b"chunk1", b"chunk2", b""])
        result = await _read_stream_limit(reader)
        assert "chunk1" in result
        assert "chunk2" in result
