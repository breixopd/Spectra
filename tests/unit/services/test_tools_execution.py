from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.execution import ensure_tool_installed, execute_via_worker
from app.services.tools.models import ToolExecutionResult


@pytest.mark.asyncio
async def test_execute_via_worker_cache_hit():
    cached_result = ToolExecutionResult(
        tool_id="nmap", target="1.2.3.4", success=True, stdout="ok", stderr="", exit_code=0, duration_seconds=1.0
    )

    with patch("app.mission.core.optimizations.tool_cache") as mock_cache:
        mock_cache.get.return_value = cached_result
        result = await execute_via_worker("nmap", "1.2.3.4", {}, None, "/tmp", "m1", "tools", 300, 30)
        assert result == cached_result
        mock_cache.get.assert_called_once_with("nmap", "1.2.3.4", {})


@pytest.mark.asyncio
async def test_execute_via_worker_success():
    mock_queue = AsyncMock()
    mock_queue.enqueue_job = AsyncMock(return_value="job-1")

    mock_job = MagicMock()
    mock_job.result = AsyncMock(return_value={
        "tool_id": "nmap",
        "target": "1.2.3.4",
        "success": True,
        "stdout": "<script>alert(1)</script>",
        "stderr": "",
        "exit_code": 0,
        "duration_seconds": 1.0,
    })

    with patch("app.mission.core.optimizations.tool_cache") as mock_cache:
        mock_cache.get.return_value = None
        with patch("app.infrastructure.queue.PostgresJobQueue", return_value=mock_queue):
            with patch("app.infrastructure.queue.Job", return_value=mock_job):
                result = await execute_via_worker("nmap", "1.2.3.4", {"-p": "80"}, 60, "/tmp", "m1", "tools", 300, 30)

    assert result.success is True
    assert result.stdout == "&lt;script&gt;alert(1)&lt;/script&gt;"
    mock_cache.set.assert_called_once()


@pytest.mark.asyncio
async def test_execute_via_worker_timeout():
    mock_queue = AsyncMock()
    mock_queue.enqueue_job = AsyncMock(return_value="job-1")

    mock_job = MagicMock()
    mock_job.result = AsyncMock(side_effect=TimeoutError)

    with patch("app.mission.core.optimizations.tool_cache") as mock_cache:
        mock_cache.get.return_value = None
        with patch("app.infrastructure.queue.PostgresJobQueue", return_value=mock_queue):
            with patch("app.infrastructure.queue.Job", return_value=mock_job):
                result = await execute_via_worker("nmap", "1.2.3.4", {}, 60, "/tmp", "m1", "tools", 300, 30)

    assert result.success is False
    assert "timed out" in result.stderr


@pytest.mark.asyncio
async def test_execute_via_worker_oom_escalation():
    mock_queue = AsyncMock()
    mock_queue.enqueue_job = AsyncMock(return_value="job-1")

    mock_job = MagicMock()
    mock_job.result = AsyncMock(side_effect=[
        {"oom": True},
        {
            "tool_id": "nmap",
            "target": "1.2.3.4",
            "success": True,
            "stdout": "ok",
            "stderr": "",
            "exit_code": 0,
            "duration_seconds": 1.0,
        },
    ])

    with patch("app.mission.core.optimizations.tool_cache") as mock_cache:
        mock_cache.get.return_value = None
        with patch("app.infrastructure.queue.PostgresJobQueue", return_value=mock_queue):
            with patch("app.infrastructure.queue.Job", return_value=mock_job):
                with patch("app.services.tools.sandbox.escalation.attempt_oom_escalation", new_callable=AsyncMock, return_value=(True, "escalated")):
                    result = await execute_via_worker("nmap", "1.2.3.4", {}, 60, "/tmp", "m1", "tools", 300, 30)

    assert result.success is True


@pytest.mark.asyncio
async def test_execute_via_worker_oom_escalation_fails():
    mock_queue = AsyncMock()
    mock_queue.enqueue_job = AsyncMock(return_value="job-1")

    mock_job = MagicMock()
    mock_job.result = AsyncMock(return_value={"oom": True})

    with patch("app.mission.core.optimizations.tool_cache") as mock_cache:
        mock_cache.get.return_value = None
        with patch("app.infrastructure.queue.PostgresJobQueue", return_value=mock_queue):
            with patch("app.infrastructure.queue.Job", return_value=mock_job):
                with patch("app.services.tools.sandbox.escalation.attempt_oom_escalation", new_callable=AsyncMock, return_value=(False, "max tier")):
                    result = await execute_via_worker("nmap", "1.2.3.4", {}, 60, "/tmp", "m1", "tools", 300, 30)

    assert result.success is False


@pytest.mark.asyncio
async def test_ensure_tool_installed_success():
    mock_queue = AsyncMock()
    mock_queue.enqueue_job = AsyncMock(return_value="job-1")

    mock_job = MagicMock()
    mock_job.result = AsyncMock(return_value={"status": "success"})

    mock_tool = MagicMock()
    mock_registry = MagicMock()
    mock_registry.get_tool.return_value = mock_tool

    with patch("app.infrastructure.queue.PostgresJobQueue", return_value=mock_queue):
        with patch("app.infrastructure.queue.Job", return_value=mock_job):
            with patch("app.services.tools.registry.get_registry", return_value=mock_registry):
                result = await ensure_tool_installed("nmap", 300)

    assert result is True
    assert mock_tool.status.value == "pending"


@pytest.mark.asyncio
async def test_ensure_tool_installed_failure():
    mock_queue = AsyncMock()
    mock_queue.enqueue_job = AsyncMock(return_value="job-1")

    mock_job = MagicMock()
    mock_job.result = AsyncMock(return_value={"status": "validation_failed"})

    with patch("app.infrastructure.queue.PostgresJobQueue", return_value=mock_queue):
        with patch("app.infrastructure.queue.Job", return_value=mock_job):
            result = await ensure_tool_installed("nmap", 300)

    assert result is False


@pytest.mark.asyncio
async def test_ensure_tool_installed_exception():
    mock_queue = AsyncMock()
    mock_queue.enqueue_job = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.infrastructure.queue.PostgresJobQueue", return_value=mock_queue):
        result = await ensure_tool_installed("nmap", 300)

    assert result is False
