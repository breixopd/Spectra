"""Unit tests for worker tool job orchestration."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.models import ToolStatus
from tests.helpers import has_async_update, make_module


def _tool(tool_id: str, *, available: bool = True, args_template: str = "", timeout: int = 5):
    execution = SimpleNamespace(
        command=f"{tool_id} --run",
        args_template=args_template,
        timeout=timeout,
        timeout_per_host=3,
        min_timeout=1,
        max_timeout=20,
        success_exit_codes=[0],
    )
    return SimpleNamespace(
        config=SimpleNamespace(id=tool_id, execution=execution),
        is_available=available,
        status=ToolStatus.READY if available else ToolStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_reload_plugins_rebuilds_golden_image_when_plugins_removed():
    from spectra_worker import tool_jobs

    registry_tools = [_tool("old-tool")]
    registry = SimpleNamespace(
        list_tools=MagicMock(side_effect=lambda: list(registry_tools)),
        load_plugins=AsyncMock(side_effect=registry_tools.clear),
    )

    with (
        pytest.MonkeyPatch.context() as mp,
        patch.object(tool_jobs, "sync_all_status_job", new=AsyncMock()),
        patch.object(tool_jobs, "build_golden_image_job", new=AsyncMock(return_value={"status": "success"})) as build,
    ):
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        result = await tool_jobs.reload_plugins_job()

    assert result["added"] == []
    assert result["removed"] == ["old-tool"]
    assert result["golden_image"] == {"status": "success"}
    build.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_tool_job_returns_not_found_error():
    from spectra_worker import tool_jobs

    registry = SimpleNamespace(get_tool=MagicMock(return_value=None))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        result = await tool_jobs.execute_tool_job("missing", "example.com")

    assert result["success"] is False
    assert result["stderr"] == "Tool not found: missing"


@pytest.mark.asyncio
async def test_execute_tool_job_fails_fast_when_tool_missing_from_image():
    from spectra_worker import tool_jobs

    registry = SimpleNamespace(get_tool=MagicMock(return_value=_tool("nmap", available=False)))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        result = await tool_jobs.execute_tool_job("nmap", "example.com")

    assert result["success"] is False
    assert "verified worker image" in result["stderr"]


@pytest.mark.asyncio
async def test_execute_tool_job_handles_command_build_failure():
    from spectra_worker import tool_jobs

    tool = _tool("nmap")
    registry = SimpleNamespace(get_tool=MagicMock(return_value=tool))

    class _Builder:
        def __init__(self, config):
            self.config = config

        def build_command(self, request, output_dir):
            raise ValueError("bad args")

    class _Parser:
        def __init__(self, config):
            self.config = config

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.adapter.builder",
            make_module("app.services.tools.adapter.builder", CommandBuilder=_Builder),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.adapter.parser",
            make_module("app.services.tools.adapter.parser", UniversalParser=_Parser),
        )
        mp.setattr(tool_jobs, "_is_tool_installed", lambda tool: True)
        result = await tool_jobs.execute_tool_job("nmap", "example.com")

    assert result["success"] is False
    assert result["stderr"] == "Command build failed: bad args"


@pytest.mark.asyncio
async def test_execute_tool_job_adjusts_cidr_timeout_and_marks_timeout_with_parse_warning(tmp_path):
    from spectra_worker import tool_jobs

    tool = _tool("nmap", args_template="--out {output_file}")
    registry = SimpleNamespace(get_tool=MagicMock(return_value=tool))
    track_stats = AsyncMock()
    run_command = AsyncMock(return_value=(124, "raw output", "stderr text"))

    class _Builder:
        def __init__(self, config):
            self.config = config

        def build_command(self, request, output_dir):
            return "scan target"

    parser = SimpleNamespace(parse_output=AsyncMock(side_effect=ValueError("bad parse")))

    class _Parser:
        def __init__(self, config):
            self.config = config

        async def parse_output(self, stdout, stderr, output_file):
            return await parser.parse_output(stdout, stderr, output_file)

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.adapter.builder",
            make_module("app.services.tools.adapter.builder", CommandBuilder=_Builder),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.adapter.parser",
            make_module("app.services.tools.adapter.parser", UniversalParser=_Parser),
        )
        mp.setattr(tool_jobs, "_run_command", run_command)
        mp.setattr(tool_jobs, "_track_tool_stats", track_stats)
        mp.setattr(tool_jobs, "_is_tool_installed", lambda tool: True)
        result = await tool_jobs.execute_tool_job("nmap", "10.0.0.0/30", output_dir=str(tmp_path))

    assert result["success"] is False
    assert result["exit_code"] == 124
    assert result["parsed_findings"] == []
    assert result["output_file"].endswith("nmap_output")
    assert "Command timed out" in result["stderr"]
    assert "12s" in result["stderr"]
    wrapped_command, wrapper_timeout = run_command.await_args.args
    assert wrapped_command.startswith("timeout -k 10s ")
    assert "12s" in wrapped_command
    assert wrapped_command.endswith("scan target")
    assert wrapper_timeout > 12
    track_stats.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_tool_job_flags_oom_results_and_returns_parsed_findings(tmp_path):
    from spectra_worker import tool_jobs

    tool = _tool("httpx")
    registry = SimpleNamespace(get_tool=MagicMock(return_value=tool))
    track_stats = AsyncMock()
    run_command = AsyncMock(return_value=(137, "scan output", "killed"))

    class _Builder:
        def __init__(self, config):
            self.config = config

        def build_command(self, request, output_dir):
            return "run httpx"

    parser = SimpleNamespace(parse_output=AsyncMock(return_value=[{"id": "finding-1"}]))

    class _Parser:
        def __init__(self, config):
            self.config = config

        async def parse_output(self, stdout, stderr, output_file):
            return await parser.parse_output(stdout, stderr, output_file)

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.adapter.builder",
            make_module("app.services.tools.adapter.builder", CommandBuilder=_Builder),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.adapter.parser",
            make_module("app.services.tools.adapter.parser", UniversalParser=_Parser),
        )
        mp.setattr(tool_jobs, "_run_command", run_command)
        mp.setattr(tool_jobs, "_track_tool_stats", track_stats)
        mp.setattr(tool_jobs, "_is_tool_installed", lambda tool: True)
        result = await tool_jobs.execute_tool_job("httpx", "example.com", output_dir=str(tmp_path))

    assert result["success"] is False
    assert result["oom"] is True
    assert result["parsed_findings"] == [{"id": "finding-1"}]


@pytest.mark.asyncio
async def test_install_tool_job_rebuilds_golden_image_and_syncs_status():
    from spectra_worker import tool_jobs

    sync_status = AsyncMock()
    build = AsyncMock(return_value={"status": "success", "image_id": "sha256:abc"})
    registry = SimpleNamespace(get_tool=MagicMock(return_value=_tool("nmap")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        mp.setattr(tool_jobs, "build_golden_image_job", build)
        mp.setattr(tool_jobs, "_is_tool_installed", MagicMock(return_value=True))
        mp.setattr(tool_jobs, "_sync_tool_status", sync_status)
        result = await tool_jobs.install_tool_job("nmap")

    assert result == {"status": "success", "image_id": "sha256:abc", "tool_id": "nmap", "success": True}
    build.assert_awaited_once()
    assert has_async_update(sync_status, "nmap", status="installing", phase="golden_image_build")
    assert has_async_update(sync_status, "nmap", status="ready", success=True)


@pytest.mark.asyncio
async def test_uninstall_tool_job_syncs_progress_and_pending_status_on_success():
    from spectra_worker import tool_jobs

    sync_status = AsyncMock()

    async def uninstall(tool_id, progress_callback):
        await progress_callback({"status": "uninstalling"})
        return {"success": True}

    installer = SimpleNamespace(uninstall=AsyncMock(side_effect=uninstall))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.installer",
            make_module("app.services.tools.installer", ToolInstaller=lambda: installer),
        )
        mp.setattr(tool_jobs, "build_golden_image_job", AsyncMock(return_value={"status": "success"}))
        mp.setattr(tool_jobs, "_sync_tool_status", sync_status)
        result = await tool_jobs.uninstall_tool_job("nmap")

    assert result == {"success": True, "golden_image": {"status": "success"}}
    assert has_async_update(sync_status, "nmap", status="uninstalling")
    assert has_async_update(sync_status, "nmap", status="pending", success=True)


@pytest.mark.asyncio
async def test_install_all_tools_job_rebuilds_golden_image_for_all_tools():
    from spectra_worker import tool_jobs

    ready_tool = _tool("ready")
    install_tool = _tool("install")
    fail_tool = _tool("fail")
    registry = SimpleNamespace(list_tools=MagicMock(return_value=[ready_tool, install_tool, fail_tool]))
    sync_status = AsyncMock()
    build = AsyncMock(return_value={"status": "success", "image_id": "sha256:abc"})

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        mp.setattr(tool_jobs, "_sync_tool_status", sync_status)
        mp.setattr(tool_jobs, "build_golden_image_job", build)
        mp.setattr(tool_jobs, "_is_tool_installed", MagicMock(return_value=True))
        result = await tool_jobs.install_all_tools_job(force=True)

    assert result == {"tools": 3, "golden_image": {"status": "success", "image_id": "sha256:abc"}, "force": True}
    build.assert_awaited_once()
    assert has_async_update(sync_status, "ready", status="ready", success=True)


@pytest.mark.asyncio
async def test_reload_plugins_job_syncs_status_and_rebuilds_for_new_tools():
    from spectra_worker import tool_jobs

    old_tool = _tool("old")
    new_tool = _tool("new")
    registry = SimpleNamespace(
        list_tools=MagicMock(side_effect=[[old_tool], [old_tool, new_tool]]),
        load_plugins=AsyncMock(),
    )
    sync_all = AsyncMock(return_value={"synced": 2, "total": 2})
    build = AsyncMock(return_value={"status": "success"})

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        mp.setattr(tool_jobs, "sync_all_status_job", sync_all)
        mp.setattr(tool_jobs, "build_golden_image_job", build)
        result = await tool_jobs.reload_plugins_job()

    assert result == {"reloaded": 2, "added": ["new"], "removed": [], "golden_image": {"status": "success"}}
    sync_all.assert_awaited_once()
    build.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_tool_status_job_reports_missing_and_installed_tools():
    from spectra_worker import tool_jobs

    tool = _tool("nmap")
    registry = SimpleNamespace(get_tool=MagicMock(side_effect=[None, tool]))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        missing = await tool_jobs.get_tool_status_job("missing")
        mp.setattr(tool_jobs, "_is_tool_installed", MagicMock(return_value=True))
        mp.setattr(tool_jobs, "_get_executable", MagicMock(return_value="nmap"))
        found = await tool_jobs.get_tool_status_job("nmap")

    assert missing == {"tool_id": "missing", "found": False, "status": "unknown"}
    assert found == {
        "tool_id": "nmap",
        "found": True,
        "status": "ready",
        "is_installed": True,
        "executable": "nmap",
    }


@pytest.mark.asyncio
async def test_sync_all_status_job_updates_every_registered_tool():
    from spectra_worker import tool_jobs

    ready_tool = _tool("ready")
    pending_tool = _tool("pending", available=False)
    registry = SimpleNamespace(list_tools=MagicMock(return_value=[ready_tool, pending_tool]))
    sync_status = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.tools.registry",
            make_module("app.services.tools.registry", get_registry=lambda: registry),
        )
        mp.setattr(tool_jobs, "_is_tool_installed", MagicMock(side_effect=[True, False]))
        mp.setattr(tool_jobs, "_sync_tool_status", sync_status)
        result = await tool_jobs.sync_all_status_job()

    assert result == {"synced": 2, "total": 2}
    assert has_async_update(sync_status, "ready", status="ready")
    assert has_async_update(sync_status, "pending", status="pending")
