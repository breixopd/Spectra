"""Test Plugin Management - Upload, Install, Uninstall, Verification."""

import asyncio

import pytest
import pytest_asyncio

from app.core.database import engine
from app.infrastructure.queue import Job
from app.services.tools.models import ToolStatus
from app.services.tools.registry import get_registry

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.live,
]

VALID_PLUGIN = {
    "id": "test-plugin",
    "name": "Test Plugin",
    "version": "1.0.0",
    "category": "custom",
    "description": "A test plugin for verification",
    "installation": {
        "method": "script",
        "commands": ["echo 'Installing test plugin'"],
        "verification_command": "echo 'test-plugin v1.0.0'",
        "verification_regex": "test-plugin v1.0.0",
    },
    "execution": {"command": "echo", "args_template": "Hello {target}", "timeout": 10},
    "parsing": {"format": "text"},
}

BROKEN_PLUGIN = {
    "id": "broken-plugin",
    "name": "Broken Plugin",
    "version": "1.0.0",
    "category": "custom",
    "description": "A broken plugin",
    "installation": {
        "method": "script",
        "commands": ["echo 'Installing broken plugin'"],
        "verification_command": "false",
        "verification_regex": "success",
    },
    "execution": {"command": "echo", "args_template": "Hello", "timeout": 10},
}


@pytest.fixture
def registry():
    """Get the real registry which points to /app/plugins (shared volume)."""
    return get_registry()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_registry(registry):
    """Ensure clean state before/after tests."""

    async def _clean():
        for tool_id in ["test-plugin", "broken-plugin"]:
            if tool_id in registry._tools:
                await registry.remove_plugin(tool_id)
            path = registry.plugins_dir / f"{tool_id}.json"
            if path.exists():
                path.unlink()

    await _clean()
    yield
    await _clean()


async def wait_for_job(job_id: str, timeout: int = 30):
    """Wait for a postgres job to complete."""
    from sqlalchemy import select as sa_select
    from app.infrastructure.queue import JobQueue
    from app.core.database import async_session_maker

    start_time = asyncio.get_running_loop().time()

    while asyncio.get_running_loop().time() - start_time < timeout:
        job = Job(job_id)
        status = await job.status()

        if status == "completed":
            return await job.result()
        elif status == "failed":
            raise Exception(f"Job {job_id} failed: {await job.result()}")
        elif status == "dead_letter":
            async with async_session_maker() as session:
                result = await session.execute(sa_select(JobQueue).where(JobQueue.id == job_id))
                row = result.scalar_one_or_none()
                error = row.error if row else "unknown"
            raise Exception(f"Job {job_id} moved to dead letter: {error}")

        await asyncio.sleep(1)

    raise TimeoutError("Job timed out")


class TestPluginLifecycle:
    """Test the full plugin lifecycle."""

    async def test_plugin_upload_and_install(self, registry):
        """Test uploading a valid plugin and its auto-installation."""
        registry.safe_mode = False
        registry.validator.safe_mode = False

        tool = await registry.add_plugin(VALID_PLUGIN)
        assert tool.status == ToolStatus.PENDING
        assert tool.config.id == "test-plugin"

        plugin_path = registry.plugins_dir / "test-plugin.json"
        assert plugin_path.exists()

        from app.infrastructure.queue import PostgresJobQueue, worker_loop
        from app.worker import _WORKER_FUNCTIONS

        pool = PostgresJobQueue()
        job_id = await pool.enqueue_job("install_tool_job", tool_id="test-plugin")
        assert job_id is not None, "Failed to enqueue installation"

        # Run worker to process the job
        worker_task = asyncio.create_task(worker_loop(_WORKER_FUNCTIONS))

        result = await wait_for_job(job_id)
        assert result["success"] is True
        assert result["tool_id"] == "test-plugin"

        print(f"Installation result: {result}")
        worker_task.cancel()
        await engine.dispose()

    async def test_broken_plugin_verification_failure(self, registry):
        """Test that a plugin with failing verification is marked as failed."""
        registry.safe_mode = False
        registry.validator.safe_mode = False

        tool = await registry.add_plugin(BROKEN_PLUGIN)
        assert tool.status == ToolStatus.PENDING

        from app.infrastructure.queue import PostgresJobQueue, worker_loop
        from app.worker import _WORKER_FUNCTIONS

        pool = PostgresJobQueue()
        job_id = await pool.enqueue_job("install_tool_job", tool_id="broken-plugin")
        assert job_id is not None, "Failed to enqueue installation"

        # Run worker to process the job
        worker_task = asyncio.create_task(worker_loop(_WORKER_FUNCTIONS))

        with pytest.raises(Exception, match="Verification command failed"):
            await wait_for_job(job_id)
        worker_task.cancel()
        await engine.dispose()

    async def test_plugin_uninstall(self, registry):
        """Test uninstalling a plugin removes it from registry and disk."""
        registry.safe_mode = False
        registry.validator.safe_mode = False

        await registry.add_plugin(VALID_PLUGIN)
        plugin_path = registry.plugins_dir / "test-plugin.json"
        assert plugin_path.exists()

        success = await registry.remove_plugin("test-plugin")
        assert success is True

        assert registry.get_tool("test-plugin") is None
        assert not plugin_path.exists()
