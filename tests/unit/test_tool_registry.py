import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
from app.services.tools.registry import ToolRegistry, ToolStatus
from app.services.tools.models import RegisteredTool, ToolConfig


@pytest.fixture
def mock_registry():
    # We initialize with safe_mode=False to avoid needing crypto keys setup
    # unless we are strictly testing that part.
    registry = ToolRegistry(plugins_dir="tests/plugins", safe_mode=False)

    # Mock the internal components
    registry.loader = AsyncMock()
    registry.installer = AsyncMock()
    registry.validator = MagicMock()

    return registry


@pytest.mark.asyncio
async def test_load_plugin_success(mock_registry):
    """Test loading a valid plugin."""
    plugin_path = MagicMock(spec=Path)
    plugin_path.stem = "test-nmap"
    plugin_path.name = "test-nmap.json"

    # Mock plugins_dir
    mock_registry.plugins_dir = MagicMock(spec=Path)
    mock_registry.plugins_dir.exists.return_value = True
    mock_registry.plugins_dir.glob.return_value = [plugin_path]

    # Mock data to return
    # Use generic mock instead of spec=RegisteredTool to allow nested attributes
    mock_tool = MagicMock()
    mock_tool.status = ToolStatus.READY
    mock_tool.config.name = "Test Tool"

    mock_registry.loader.load_plugins.return_value = {"test-tool": mock_tool}

    tools = await mock_registry.load_plugins()

    assert "test-tool" in tools
    assert tools["test-tool"] == mock_tool


@pytest.mark.asyncio
async def test_install_tool_success(mock_registry):
    """Test installation delegates to installer."""
    mock_registry._tools["tool"] = MagicMock()  # No spec
    mock_registry._tools["tool"].config.id = "tool"
    mock_registry.installer.install_tool.return_value = True

    result = await mock_registry.install_tool("tool")

    assert result is True
    mock_registry.installer.install_tool.assert_called_once()


@pytest.mark.asyncio
async def test_remove_plugin(mock_registry):
    """Test removal logic."""
    mock_registry._tools["tool-id"] = MagicMock()  # No spec
    mock_registry._tools["tool-id"].config.is_system = False

    # Mock plugins_dir behaviors
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.is_file.return_value = True
    # resolve() check in code: resolved.parent == self.plugins_dir.resolve()
    mock_path.resolve.return_value.parent = mock_registry.plugins_dir.resolve()

    # We need to mock the path construction: self.plugins_dir / f"{tool_id}.json"
    mock_registry.plugins_dir = MagicMock()
    mock_registry.plugins_dir.resolve.return_value = MagicMock()
    mock_registry.plugins_dir.__truediv__.return_value = mock_path

    success = await mock_registry.remove_plugin("tool-id")

    assert success is True
    assert "tool-id" not in mock_registry._tools
    mock_path.unlink.assert_called_once()


def test_validate_plugin_delegates_to_validator(mock_registry):
    """Test that validate_plugin delegates to the validator component."""
    data = {"id": "test"}
    mock_registry.validator.validate_plugin.return_value = ToolConfig(
        id="test",
        name="Test",
        version="1.0.0",
        category="discovery",
        description="test",
        execution={"command": "echo", "args_template": ""},
        metadata={"capabilities": [], "risk_level": "low", "ai_description": ""},
    )

    result = mock_registry.validate_plugin(data)

    assert result.id == "test"
    mock_registry.validator.validate_plugin.assert_called_once_with(data)
