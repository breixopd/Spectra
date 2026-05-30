"""Unit tests for worker lifecycle, command, and VPN jobs."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import make_module


def _tool(tool_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            id=tool_id,
            execution=SimpleNamespace(command=f"{tool_id} --run"),
        ),
        status=None,
    )


@pytest.mark.asyncio
async def test_worker_startup_initializes_registry_and_auto_install():
    from spectra_worker import lifecycle

    registry = SimpleNamespace(list_tools=MagicMock(return_value=[_tool("demo")]))
    auto_install = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "spectra_tools_core.registry",
            make_module("spectra_tools_core.registry", initialize_registry=AsyncMock(return_value=registry)),
        )
        mp.setattr(lifecycle, "_auto_install_pending", auto_install)
        await lifecycle.startup()

    auto_install.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_startup_returns_when_registry_init_fails():
    from spectra_worker import lifecycle

    auto_install = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "spectra_tools_core.registry",
            make_module("spectra_tools_core.registry", initialize_registry=AsyncMock(side_effect=ImportError("bad"))),
        )
        mp.setattr(lifecycle, "_auto_install_pending", auto_install)
        await lifecycle.startup()

    auto_install.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_install_pending_syncs_detected_status_without_installing():
    from spectra_worker import lifecycle

    ready_tool = _tool("ready-tool")
    missing_tool = _tool("missing-tool")
    tools = [ready_tool, missing_tool]
    registry = SimpleNamespace(list_tools=MagicMock(return_value=tools))
    installer_factory = MagicMock()

    batch_sync = AsyncMock(return_value=["missing-tool"])

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "spectra_tools_core.registry",
            make_module("spectra_tools_core.registry", get_registry=lambda: registry),
        )
        mp.setitem(
            sys.modules,
            "spectra_tools.installer",
            make_module("spectra_tools.installer", ToolInstaller=installer_factory),
        )
        mp.setattr(lifecycle, "_batch_sync_tool_statuses", batch_sync)
        await lifecycle._auto_install_pending()

    batch_sync.assert_awaited_once()
    installer_factory.assert_not_called()


@pytest.mark.asyncio
async def test_worker_shutdown_disposes_database_engine():
    from spectra_worker import lifecycle

    engine = SimpleNamespace(dispose=AsyncMock())

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "spectra_persistence.database", make_module("spectra_persistence.database", engine=engine))
        await lifecycle.shutdown()

    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_shutdown_ignores_dispose_errors():
    from spectra_worker import lifecycle

    engine = SimpleNamespace(dispose=AsyncMock(side_effect=OSError("db busy")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "spectra_persistence.database", make_module("spectra_persistence.database", engine=engine))
        await lifecycle.shutdown()

    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_heartbeat_loop_updates_db_before_cancellation():
    from spectra_worker import lifecycle

    session = AsyncMock()
    session.commit = AsyncMock()
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    sandbox_model = type("Sandbox", (), {"queue_name": "queue", "status": "running"})

    class _FakeUpdate:
        def where(self, *args, **kwargs):
            return self

        def values(self, **kwargs):
            return self

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sqlalchemy.update", lambda *args, **kwargs: _FakeUpdate())
        mp.setitem(
            sys.modules,
            "spectra_persistence.database",
            make_module("spectra_persistence.database", async_session_maker=MagicMock(return_value=session_ctx)),
        )
        mp.setitem(
            sys.modules,
            "spectra_persistence.models.infrastructure",
            make_module("spectra_persistence.models.infrastructure", Sandbox=sandbox_model),
        )
        mp.setattr(lifecycle.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))
        with pytest.raises(asyncio.CancelledError):
            await lifecycle.heartbeat_loop("queue", interval=0)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_heartbeat_loop_logs_and_retries_after_db_error():
    from spectra_worker import lifecycle

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    sandbox_model = type("Sandbox", (), {"queue_name": "queue", "status": "running"})

    class _FakeUpdate:
        def where(self, *args, **kwargs):
            return self

        def values(self, **kwargs):
            return self

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sqlalchemy.update", lambda *args, **kwargs: _FakeUpdate())
        mp.setitem(
            sys.modules,
            "spectra_persistence.database",
            make_module("spectra_persistence.database", async_session_maker=MagicMock(return_value=session_ctx)),
        )
        mp.setitem(
            sys.modules,
            "spectra_persistence.models.infrastructure",
            make_module("spectra_persistence.models.infrastructure", Sandbox=sandbox_model),
        )
        mp.setattr(lifecycle.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))
        with pytest.raises(asyncio.CancelledError):
            await lifecycle.heartbeat_loop("queue", interval=0)

    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_command_job_blocks_unsafe_commands():
    from spectra_worker import command_jobs

    class _SafetySupervisorAgent:
        @staticmethod
        def check_blocklist(command):
            return (False, "dangerous")

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "spectra_ai_core.agents.safety",
            make_module("spectra_ai_core.agents.safety", SafetySupervisorAgent=_SafetySupervisorAgent),
        )
        run_command = AsyncMock()
        mp.setattr(command_jobs, "_run_command", run_command)
        result = await command_jobs.run_command_job("rm -rf /", timeout=10)

    assert result == {
        "success": False,
        "exit_code": -1,
        "stdout": "",
        "stderr": "Blocked by safety check: dangerous",
    }
    run_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_command_job_wraps_command_with_timeout():
    from spectra_worker import command_jobs

    class _SafetySupervisorAgent:
        @staticmethod
        def check_blocklist(command):
            return (True, "")

    run_command = AsyncMock(return_value=(0, "done", ""))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "spectra_ai_core.agents.safety",
            make_module("spectra_ai_core.agents.safety", SafetySupervisorAgent=_SafetySupervisorAgent),
        )
        mp.setattr(command_jobs, "_run_command", run_command)
        result = await command_jobs.run_command_job("echo hi", timeout=10, cwd="/tmp/work")

    assert result["success"] is True
    wrapped_command, wrapper_timeout, wrapper_cwd = run_command.await_args.args
    assert wrapped_command.startswith("timeout -k 10s ")
    assert "echo hi" in wrapped_command
    assert wrapper_timeout > 10
    assert wrapper_cwd == "/tmp/work"


@pytest.mark.asyncio
async def test_execute_script_job_runs_python_script_successfully():
    from spectra_worker import command_jobs

    run_command = AsyncMock(return_value=(0, "python ok", ""))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(command_jobs, "_run_command", run_command)
        result = await command_jobs.execute_script_job(
            content="print('hello')",
            language="python",
            target="127.0.0.1",
            args=["--flag"],
            timeout=5,
        )

    assert result["success"] is True
    wrapped = run_command.await_args.args[0]
    assert wrapped[:4] == ["timeout", "-k", "10s", "5s"]
    assert wrapped[-2:] == ["127.0.0.1", "--flag"]


@pytest.mark.asyncio
async def test_execute_script_job_reports_go_compilation_failure():
    from spectra_worker import command_jobs

    run_command = AsyncMock(return_value=(1, "", "compile failed"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(command_jobs, "_run_command", run_command)
        result = await command_jobs.execute_script_job(
            content="package main",
            language="go",
            target="127.0.0.1",
        )

    assert result["success"] is False
    assert result["stderr"] == "Compilation failed: compile failed"


@pytest.mark.asyncio
async def test_execute_script_job_runs_bash_script_successfully():
    from spectra_worker import command_jobs

    run_command = AsyncMock(side_effect=[(0, "", ""), (0, "bash ok", "")])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(command_jobs, "_run_command", run_command)
        result = await command_jobs.execute_script_job(
            content="#!/usr/bin/env bash\necho ok",
            language="bash",
            target="127.0.0.1",
        )

    assert result["success"] is True
    assert run_command.await_count == 2


@pytest.mark.asyncio
async def test_execute_script_job_rejects_unsupported_language():
    from spectra_worker import command_jobs

    result = await command_jobs.execute_script_job("puts 'hi'", "ruby", "127.0.0.1")

    assert result == {
        "success": False,
        "exit_code": -1,
        "stdout": "",
        "stderr": "Unsupported language: ruby",
    }


@pytest.mark.asyncio
async def test_execute_script_job_returns_runtime_error_details():
    from spectra_worker import command_jobs

    run_command = AsyncMock(side_effect=OSError("interpreter missing"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(command_jobs, "_run_command", run_command)
        result = await command_jobs.execute_script_job("print('hi')", "python", "127.0.0.1")

    assert result["success"] is False
    assert result["stderr"] == "interpreter missing"


@pytest.mark.asyncio
async def test_execute_script_job_ignores_cleanup_failures():
    from spectra_worker import command_jobs

    run_command = AsyncMock(return_value=(0, "ok", ""))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(command_jobs, "_run_command", run_command)
        mp.setattr(command_jobs.shutil, "rmtree", MagicMock(side_effect=OSError("busy")))
        result = await command_jobs.execute_script_job("print('hi')", "python", "127.0.0.1")

    assert result["success"] is True


@pytest.mark.asyncio
async def test_vpn_connect_job_handles_supported_unknown_and_error_cases():
    from spectra_worker import vpn_jobs

    run_command = AsyncMock(side_effect=[(0, "wg up", ""), (0, "ovpn up", ""), OSError("broken")])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vpn_jobs, "_run_command", run_command)
        # Use bare filenames — _resolve_config_path strips directories
        wireguard = await vpn_jobs.vpn_connect_job("test.conf", "wireguard")
        openvpn = await vpn_jobs.vpn_connect_job("test.ovpn", "openvpn")
        unknown = await vpn_jobs.vpn_connect_job("test.conf", "pptp")
        errored = await vpn_jobs.vpn_connect_job("test.conf", "wireguard")

    assert wireguard["success"] is True
    assert openvpn["type"] == "openvpn"
    assert unknown == {"success": False, "error": "Unknown VPN type: pptp"}
    assert errored == {"success": False, "error": "broken"}


@pytest.mark.asyncio
async def test_vpn_disconnect_job_handles_supported_unknown_and_error_cases():
    from spectra_worker import vpn_jobs

    run_command = AsyncMock(side_effect=[(0, "wg down", ""), OSError("broken")])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vpn_jobs, "_run_command", run_command)
        mp.setattr(vpn_jobs.Path, "read_text", MagicMock(side_effect=FileNotFoundError()))
        mp.setattr(vpn_jobs.os, "kill", MagicMock())
        mp.setitem(
            sys.modules,
            "spectra_common.config",
            make_module("spectra_common.config", settings=SimpleNamespace(VPN_CONFIG_DIR="/vpn")),
        )
        wireguard = await vpn_jobs.vpn_disconnect_job("client", "wireguard")
        openvpn = await vpn_jobs.vpn_disconnect_job("client", "openvpn")
        unknown = await vpn_jobs.vpn_disconnect_job("client", "pptp")
        errored = await vpn_jobs.vpn_disconnect_job("client", "wireguard")

    assert wireguard["success"] is True
    assert openvpn["type"] == "openvpn"
    assert openvpn["success"] is True
    assert openvpn["stdout"] == "no pid file"
    assert unknown == {"success": False, "error": "Unknown VPN type: pptp"}
    assert errored == {"success": False, "error": "broken"}


@pytest.mark.asyncio
async def test_vpn_status_job_covers_wireguard_openvpn_absent_and_error_paths():
    from spectra_worker import vpn_jobs

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            vpn_jobs,
            "_run_command",
            AsyncMock(side_effect=[(0, "wg0", ""), (1, "", ""), (0, "1.2.3.4", "")]),
        )
        wireguard = await vpn_jobs.vpn_status_job()

    assert wireguard == {
        "connected": True,
        "interfaces": ["wg0"],
        "type": "wireguard",
        "interface": "wg0",
        "public_ip": "1.2.3.4",
    }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            vpn_jobs,
            "_run_command",
            AsyncMock(side_effect=[(1, "", ""), (0, "tun0", ""), (0, "5.6.7.8", "")]),
        )
        openvpn = await vpn_jobs.vpn_status_job()

    assert openvpn == {
        "connected": True,
        "interfaces": ["tun0"],
        "type": "openvpn",
        "interface": "tun0",
        "public_ip": "5.6.7.8",
    }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vpn_jobs, "_run_command", AsyncMock(side_effect=[(1, "", ""), (1, "", "")]))
        absent = await vpn_jobs.vpn_status_job()

    assert absent == {"connected": False, "interfaces": []}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vpn_jobs, "_run_command", AsyncMock(side_effect=RuntimeError("network unavailable")))
        errored = await vpn_jobs.vpn_status_job()

    assert errored == {
        "connected": False,
        "interfaces": [],
        "error": "network unavailable",
    }


@pytest.mark.asyncio
async def test_vpn_test_job_reports_success_failure_and_error():
    from spectra_worker import vpn_jobs

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vpn_jobs, "_run_command", AsyncMock(return_value=(0, "9.9.9.9", "")))
        success = await vpn_jobs.vpn_test_job()

    assert success == {
        "success": True,
        "public_ip": "9.9.9.9",
        "message": "VPN connectivity confirmed",
    }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vpn_jobs, "_run_command", AsyncMock(return_value=(1, "", "no route")))
        failure = await vpn_jobs.vpn_test_job()

    assert failure == {
        "success": False,
        "public_ip": None,
        "message": "Connectivity check failed: no route",
    }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vpn_jobs, "_run_command", AsyncMock(side_effect=ValueError("curl missing")))
        errored = await vpn_jobs.vpn_test_job()

    assert errored == {"success": False, "error": "curl missing"}
