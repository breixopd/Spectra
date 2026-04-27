import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.worker.helpers import (
    _error_result,
    _get_executable,
    _is_tool_installed,
    _build_process_env,
    _decode_process_output,
    _status_field,
    _merge_status_logs,
    _build_tool_status_payload,
    _run_command,
    _track_tool_stats,
    _sync_tool_status,
)


def test_error_result():
    result = _error_result("nmap", "1.2.3.4", "connection failed")
    assert result["tool_id"] == "nmap"
    assert result["target"] == "1.2.3.4"
    assert result["success"] is False
    assert result["exit_code"] == -1
    assert "connection failed" in result["stderr"]


def test_get_executable():
    tool = MagicMock()
    tool.config.execution.command = "nmap -sV"
    assert _get_executable(tool) == "nmap"


def test_get_executable_empty():
    tool = MagicMock()
    tool.config.execution.command = ""
    tool.config.id = "custom-tool"
    assert _get_executable(tool) == "custom-tool"


def test_is_tool_installed_in_path():
    tool = MagicMock()
    tool.config.execution.command = "python3"
    assert _is_tool_installed(tool) is True


def test_is_tool_installed_not_found():
    tool = MagicMock()
    tool.config.execution.command = "not_a_real_tool_12345"
    assert _is_tool_installed(tool) is False


def test_build_process_env():
    env = _build_process_env()
    assert env["DEBIAN_FRONTEND"] == "noninteractive"
    assert "/opt/spectra_tools" in env["PATH"]


def test_decode_process_output():
    assert _decode_process_output(b"hello") == "hello"
    assert _decode_process_output(b"\xff\xfe") == "\ufffd\ufffd"


def test_status_field():
    result = {"key": "val"}
    existing = {}
    assert _status_field(result, existing, "key") == "val"
    assert _status_field(result, existing, "missing") == ""


def test_merge_status_logs():
    logs = _merge_status_logs(["old"], "new log")
    assert len(logs) == 2
    assert "old" in logs[0]
    assert "new log" in logs[1]


def test_merge_status_logs_empty():
    logs = _merge_status_logs([], "")
    assert logs == []


def test_merge_status_logs_not_string():
    logs = _merge_status_logs(["old"], None)
    assert logs == ["old"]


def test_build_tool_status_payload():
    existing = {"logs": ["old log"]}
    result = {"status": "running", "log_entry": "new log", "command_index": 5}
    payload = _build_tool_status_payload(existing, result)
    assert payload["status"] == "running"
    assert payload["command_index"] == 5
    assert len(payload["logs"]) == 2


def test_build_tool_status_payload_defaults():
    existing = {}
    result = {}
    payload = _build_tool_status_payload(existing, result)
    assert payload["status"] == "unknown"
    assert payload["error"] == ""
    assert payload["logs"] == []


@pytest.mark.asyncio
async def test_run_command_with_list():
    result = await _run_command(["echo", "hello"], timeout=5)
    assert result[0] == 0
    assert "hello" in result[1]


@pytest.mark.asyncio
async def test_run_command_timeout():
    result = await _run_command("sleep 10", timeout=1)
    assert result[0] == -1
    assert "timed out" in result[2]


@pytest.mark.asyncio
async def test_run_command_start_failure():
    with patch("app.worker.helpers._start_process", side_effect=OSError("cannot start")):
        result = await _run_command("false", timeout=5)
    assert result[0] == -1
    assert "cannot start" in result[2]


@pytest.mark.asyncio
async def test_track_tool_stats():
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    with patch("app.infrastructure.cache.CacheService", return_value=mock_cache):
        await _track_tool_stats("nmap", True, 1.5)

    mock_cache.set.assert_awaited_once()
    args = mock_cache.set.call_args
    assert args[0][0] == "spectra:tool_stats:nmap"


@pytest.mark.asyncio
async def test_sync_tool_status():
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={"status": "old"})

    with patch("app.infrastructure.cache.CacheService", return_value=mock_cache):
        await _sync_tool_status("nmap", {"status": "running"})

    mock_cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_track_tool_stats_failure():
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    with patch("app.infrastructure.cache.CacheService", return_value=mock_cache):
        await _track_tool_stats("nmap", False, 1.5)

    args = mock_cache.set.call_args
    assert args[0][1]["fail_count"] == 1


@pytest.mark.asyncio
async def test_track_tool_stats_exception():
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(side_effect=ConnectionError("cache down"))

    with patch("app.infrastructure.cache.CacheService", return_value=mock_cache):
        await _track_tool_stats("nmap", True, 1.5)

    mock_cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_sync_tool_status_non_dict_existing():
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value="not a dict")

    with patch("app.infrastructure.cache.CacheService", return_value=mock_cache):
        await _sync_tool_status("nmap", {"status": "running"})

    mock_cache.set.assert_awaited_once()
