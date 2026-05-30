"""Tests for plugin safety (command blocklist)."""

from __future__ import annotations

import pytest

from spectra_tools_core.registry import (
    PluginValidationError,
    ToolRegistry,
)


@pytest.fixture
def registry(tmp_path):
    """Create a registry instance."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    return ToolRegistry(plugins_dir=plugins_dir)


@pytest.mark.asyncio
async def test_dangerous_command(registry):
    """Test loading a plugin with dangerous commands."""
    plugin_data = {
        "id": "evil-tool",
        "name": "Evil Tool",
        "description": "A test tool",
        "category": "custom",
        "version": "1.0.0",
        "author": "Test",
        "execution": {"command": "echo", "args_template": "{target}", "timeout": 5},
        "installation": {"method": "script", "commands": ["rm -rf /"]},
    }

    with pytest.raises(PluginValidationError, match="Dangerous command"):
        registry.validate_plugin(plugin_data)
