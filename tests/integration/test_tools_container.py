"""Integration tests for the tools container and plugin system."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from spectra_tools.adapter import CommandToolAdapter, ToolExecutionRequest
from spectra_tools_core.registry import get_registry

if TYPE_CHECKING:
    from spectra_tools_core.registry import ToolRegistry

pytestmark = pytest.mark.integration


@pytest.fixture
def tool_registry() -> ToolRegistry:
    """Get the tool registry singleton."""
    registry = get_registry()
    return registry


@pytest.mark.asyncio
async def test_load_all_plugins(tool_registry: ToolRegistry) -> None:
    """Test that all plugins in the plugins directory can be loaded."""
    plugins_dir = Path("plugins")
    plugin_files = list(plugins_dir.glob("*.json"))

    assert plugin_files, "No plugins found in plugins directory"

    # Force reload with safe mode disabled
    await tool_registry.load_plugins()

    for plugin_file in plugin_files:
        data = json.loads(plugin_file.read_text(encoding="utf-8"))
        tool_id = data.get("id")

        if not tool_id:
            pytest.fail(f"Plugin {plugin_file} missing 'id' field")

        tool = tool_registry.get_tool(tool_id)
        assert tool is not None, f"Failed to load plugin {tool_id} from {plugin_file}"
        assert tool.config.name == data.get("name")


@pytest.mark.asyncio
async def test_execute_tool_version(tool_registry: ToolRegistry) -> None:
    """Test executing a simple command (version check) for available tools."""
    from spectra_tools_core.models import (
        ExecutionConfig,
        InstallationConfig,
        InstallationMethod,
        ToolCategory,
        ToolConfig,
    )

    dummy_config = ToolConfig(
        id="test-echo",
        name="Test Echo",
        description="Echo test",
        category=ToolCategory.CUSTOM,
        version="1.0.0",
        execution=ExecutionConfig(
            command="echo",
            args_template="{target}",
            timeout=5,
            working_dir=None,
            env={},
        ),
        installation=InstallationConfig(
            method=InstallationMethod.NONE,
            commands=[],
            verification_command=None,
            verification_regex=None,
        ),
        signature=None,
        is_system=False,
    )

    adapter = CommandToolAdapter(dummy_config)
    request = ToolExecutionRequest(
        tool_id="test-echo",
        target="hello world",
        args={},
        timeout=5,
    )

    result = await adapter.execute(request)

    assert result.success
    assert "hello world" in result.stdout


@pytest.mark.asyncio
async def test_hot_load_plugin(tool_registry: ToolRegistry) -> None:
    """Test adding a new plugin file and verifying it loads."""
    plugins_dir = Path("plugins")
    new_plugin_path = plugins_dir / "test_hot_load.json"

    # Check if writable by attempting to create a temp file
    try:
        test_file = plugins_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
    except OSError:
        pytest.skip("Plugins directory is read-only")

    plugin_data = {
        "id": "hot-load-test",
        "name": "Hot Load Test",
        "description": "Test hot loading",
        "category": "custom",
        "version": "1.0.0",
        "author": "Test",
        "execution": {
            "command": "echo",
            "args_template": "{target}",
            "timeout": 5,
        },
        "installation": {
            "method": "none",
            "commands": [],
        },
    }

    try:
        # Write new plugin
        new_plugin_path.write_text(json.dumps(plugin_data, indent=2), encoding="utf-8")

        # Trigger reload
        await tool_registry.load_plugins()

        # Verify it exists
        tool = tool_registry.get_tool("hot-load-test")
        assert tool is not None, "Hot-loaded plugin was not found"
        assert tool.config.name == "Hot Load Test"

    finally:
        # Cleanup: always remove file and restore state
        if new_plugin_path.exists():
            new_plugin_path.unlink()

        # Reload to clear the registry of test plugin
        await tool_registry.load_plugins()
        assert tool_registry.get_tool("hot-load-test") is None, "Test plugin was not removed after cleanup"
